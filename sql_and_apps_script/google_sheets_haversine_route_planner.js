/**
 * ============================================================================
 * PROPERTY LEADS SMART ROUTE PLANNER (GOOGLE APPS SCRIPT)
 * ============================================================================
 * Reference implementation for a field-service / real-estate lead sheet laid out as:
 * - Col A (Idx 0): Lead Status (Filters OUT "Under Contract" & "Taken care of";
 *                  prioritizes "JEWEL", "Hot", "For Verification", "New",
 *                  "Working on it", and "In Progress").
 * - Col B (Idx 1): Owner Name
 * - Col C (Idx 2): Phone
 * - Col F (Idx 5): Property Address
 * - Col G (Idx 6): Contacted?
 * - Col H (Idx 7): County
 * - Col K (Idx 10): Occupied or Vacant
 * - Col N (Idx 13): Equity
 * - Col O (Idx 14): Comment / Lead Notes
 * - Col P (Idx 15): Visited Status & Last Visited Timestamp (Auto-tracked)
 *
 * Stop order comes from the built-in Maps service (DirectionFinder with
 * optimizeWaypoints), not from a local Haversine/TSP calculation; the file name
 * is kept so existing links keep working. Not tested against a live sheet.
 */

const CONFIG = {
  LEADS_SHEET_NAME: "Sheet1",
  PLANNER_SHEET_NAME: "Route_Planner_Dashboard",
  PRINT_SHEET_NAME: "Printable_Route_Sheet",
  DEFAULT_START_LOCATION: "", // Optional fallback when Planner!B2 is empty, e.g. "123 Main St, Anytown"
  MINUTES_PER_STOP: 12, // Configurable dwell time at each property
  MAX_WAYPOINTS: 23,    // Google Maps Directions API waypoint ceiling per leg
  MAX_URL_WAYPOINTS: 9, // Google Maps URLs accept at most 9 waypoints (fewer on mobile browsers)
  SKIP_STATUSES: ["under contract", "taken care of", "visited", "dead"],
  PRIORITY_WEIGHTS: {
    "jewel": 100,
    "hot": 90,
    "for verification": 80,
    "scheduled appt": 75,
    "new": 70,
    "working on it": 60,
    "in progress": 50,
    "bid at auction": 40
  }
};

/**
 * Adds a 1-click menu inside Google Sheets on open.
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚗 Smart Route Planner")
    .addItem("1. Setup Route Planner Inputs", "setupPlannerTabs")
    .addItem("2. Build Optimized Driving Route", "generateSmartPropertyRoute")
    .addItem("3. Mark Completed Stops as Visited", "markCheckedStopsVisited")
    .addToUi();
}

/**
 * Creates (or returns) the planner tab with its input cells B2:B6.
 */
function setupPlannerTabs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let planner = ss.getSheetByName(CONFIG.PLANNER_SHEET_NAME);
  if (!planner) {
    planner = ss.insertSheet(CONFIG.PLANNER_SHEET_NAME);
    planner.getRange("A1:B6").setValues([
      ["Route planner input", "Value"],
      ["Start location", CONFIG.DEFAULT_START_LOCATION],
      ["End location (blank = back to start)", ""],
      ["Available hours", 2],
      ["Minutes per stop", CONFIG.MINUTES_PER_STOP],
      ["County filter (ALL or a county name)", "ALL"]
    ]);
    planner.setColumnWidth(1, 280);
  }
  if (!ss.getSheetByName(CONFIG.PRINT_SHEET_NAME)) {
    ss.insertSheet(CONFIG.PRINT_SHEET_NAME);
  }
  return planner;
}

/**
 * Copies ticked stops from the printable sheet back to the leads sheet:
 * writes "Visited <timestamp>" into column P of each ticked lead row.
 */
function markCheckedStopsVisited() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const printSheet = ss.getSheetByName(CONFIG.PRINT_SHEET_NAME);
  if (!printSheet || printSheet.getLastRow() < 2) {
    SpreadsheetApp.getUi().alert("Build a route first (menu item 2).");
    return;
  }
  const leadsSheet = getLeadsSheet_(ss);
  const rows = printSheet.getRange(2, 1, printSheet.getLastRow() - 1, 11).getValues();
  const stamp = "Visited " + Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), "yyyy-MM-dd HH:mm");
  let marked = 0;
  rows.forEach(row => {
    const ticked = row[9] === true || String(row[9]).toUpperCase() === "TRUE";
    const leadRow = parseInt(row[10], 10);
    if (ticked && leadRow > 1) {
      leadsSheet.getRange(leadRow, 16).setValue(stamp);
      marked++;
    }
  });
  SpreadsheetApp.getUi().alert(marked + " stop(s) marked as visited.");
}

function getLeadsSheet_(ss) {
  return ss.getSheetByName(CONFIG.LEADS_SHEET_NAME) || ss.getSheets()[0];
}

/**
 * Main Engine: Reads Start/End/Available Hours, scores unvisited leads,
 * packs the highest-value cluster within the time budget, calls native
 * Maps.newDirectionFinder() with optimizeWaypoints(true), and builds the
 * Printable Route Sheet + clickable Google Maps navigation link.
 */
function generateSmartPropertyRoute() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const leadsSheet = getLeadsSheet_(ss);
  const plannerSheet = ss.getSheetByName(CONFIG.PLANNER_SHEET_NAME) || setupPlannerTabs();
  const printSheet = ss.getSheetByName(CONFIG.PRINT_SHEET_NAME) || ss.insertSheet(CONFIG.PRINT_SHEET_NAME);

  // 1. Read user inputs from Planner Dashboard
  const startLocation = String(plannerSheet.getRange("B2").getValue() || CONFIG.DEFAULT_START_LOCATION).trim();
  if (!startLocation) {
    SpreadsheetApp.getUi().alert(
      "Enter a start location in " + CONFIG.PLANNER_SHEET_NAME + "!B2 (or set CONFIG.DEFAULT_START_LOCATION)."
    );
    return;
  }
  const endLocation = String(plannerSheet.getRange("B3").getValue() || startLocation).trim();
  const availableHours = parseFloat(plannerSheet.getRange("B4").getValue() || 2.0);
  const dwellMinutes = parseFloat(plannerSheet.getRange("B5").getValue() || CONFIG.MINUTES_PER_STOP);
  const countyFilter = String(plannerSheet.getRange("B6").getValue() || "ALL").trim().toUpperCase();

  const totalBudgetSeconds = Math.max(30, availableHours * 60) * 60;
  const dwellSecondsPerStop = dwellMinutes * 60;

  // 2. Load all rows from the main property leads sheet
  const data = leadsSheet.getDataRange().getValues();
  const candidates = [];

  for (let r = 1; r < data.length; r++) {
    const row = data[r];
    const rawStatus = String(row[0] || "").trim();
    const statusKey = rawStatus.toLowerCase();
    const address = String(row[5] || "").replace(/\s+/g, " ").trim();
    const county = String(row[7] || "").trim();
    const visitedFlag = String(row[15] || "").trim().toLowerCase();

    if (!address) continue;
    if (CONFIG.SKIP_STATUSES.indexOf(statusKey) !== -1) continue;
    if (visitedFlag.indexOf("visited") !== -1) continue;
    if (countyFilter !== "ALL" && county.toUpperCase() !== countyFilter) continue;

    const priorityScore = CONFIG.PRIORITY_WEIGHTS[statusKey] || 30;
    candidates.push({
      sheetRow: r + 1,
      status: rawStatus || "Active",
      ownerName: String(row[1] || "").replace(/\s+/g, " ").trim(),
      phone: String(row[2] || "").replace(/\s+/g, " ").trim(),
      address: address,
      contacted: String(row[6] || "").trim(),
      county: county,
      occupancy: String(row[10] || "").trim(),
      equity: String(row[13] || "").trim(),
      notes: String(row[14] || "").replace(/\s+/g, " ").trim(),
      priorityScore: priorityScore
    });
  }

  if (candidates.length === 0) {
    SpreadsheetApp.getUi().alert("No unvisited properties matched your filter.");
    return;
  }

  // 3. Score & pre-select candidate pool by proximity + status priority (Hot/JEWEL first)
  candidates.sort((a, b) => b.priorityScore - a.priorityScore);
  const maxStopsByTime = Math.min(
    CONFIG.MAX_WAYPOINTS,
    Math.max(1, Math.floor((availableHours * 60) / (dwellMinutes + 8)))
  );
  const selectedPool = candidates.slice(0, maxStopsByTime);

  // 4. Optimize driving sequence via built-in Google Maps DirectionFinder
  const finder = Maps.newDirectionFinder()
    .setOrigin(startLocation)
    .setDestination(endLocation)
    .setMode(Maps.DirectionFinder.Mode.DRIVING)
    .setOptimizeWaypoints(true);

  selectedPool.forEach(item => finder.addWaypoint(item.address));

  const directions = finder.getDirections();
  if (!directions.routes || directions.routes.length === 0) {
    throw new Error("Google Maps could not compute a route. Check address formatting.");
  }

  const route = directions.routes[0];
  const waypointOrder = route.waypoint_order; // Optimized visit order indices
  const legs = route.legs;

  // 5. Trim stops dynamically so cumulative Drive Time + Stop Dwell Time <= Available Time
  const finalStops = [];
  let cumulativeSeconds = 0;

  for (let i = 0; i < waypointOrder.length; i++) {
    const candidateIdx = waypointOrder[i];
    const prop = selectedPool[candidateIdx];
    const leg = legs[i];
    const legDriveSeconds = leg ? leg.duration.value : 600;
    const legMiles = leg ? (leg.distance.value / 1609.34).toFixed(1) : "0.0";

    if (cumulativeSeconds + legDriveSeconds + dwellSecondsPerStop > totalBudgetSeconds && finalStops.length > 0) {
      break;
    }

    cumulativeSeconds += legDriveSeconds + dwellSecondsPerStop;
    finalStops.push({
      stopNumber: finalStops.length + 1,
      driveTimeMins: Math.round(legDriveSeconds / 60),
      distanceMiles: legMiles,
      cumulativeMins: Math.round(cumulativeSeconds / 60),
      prop: prop
    });
  }

  // 6. Build Multi-Stop Google Maps Navigation Path (Opens directly in Google Maps App)
  const encodedOrigin = encodeURIComponent(startLocation);
  const encodedDest = encodeURIComponent(endLocation);
  const urlStops = finalStops.slice(0, CONFIG.MAX_URL_WAYPOINTS);
  const encodedWaypoints = urlStops.map(s => encodeURIComponent(s.prop.address)).join("|");
  const navUrl = "https://www.google.com/maps/dir/?api=1&origin=" + encodedOrigin +
                 "&destination=" + encodedDest + "&travelmode=driving&waypoints=" + encodedWaypoints;

  // 7. Render Printable Route Sheet
  printSheet.clearContents();
  printSheet.getRange("A1:K1").setValues([[
    "Stop #", "Status", "Drive Mins", "Miles", "Property Address",
    "Owner Name", "Phone Number", "County / Occupancy", "Equity / Lead Notes", "Visited? (Check)",
    "Lead Row"
  ]]);

  const outputRows = finalStops.map(s => [
    "Stop #" + s.stopNumber + " (" + s.cumulativeMins + "m elapsed)",
    s.prop.status,
    s.driveTimeMins + " mins",
    s.distanceMiles + " mi",
    s.prop.address,
    s.prop.ownerName,
    s.prop.phone,
    s.prop.county + (s.prop.occupancy ? " / " + s.prop.occupancy : ""),
    (s.prop.equity ? "Eq: " + s.prop.equity + " | " : "") + s.prop.notes,
    false,
    s.prop.sheetRow
  ]);

  if (outputRows.length > 0) {
    printSheet.getRange(2, 1, outputRows.length, 11).setValues(outputRows);
    printSheet.getRange(2, 10, outputRows.length, 1).insertCheckboxes();
  }
  printSheet.getRange(outputRows.length + 3, 1).setValue("CLICK TO OPEN TURN-BY-TURN GOOGLE MAPS ROUTE:");
  printSheet.getRange(outputRows.length + 3, 2).setValue(navUrl);
  if (finalStops.length > urlStops.length) {
    printSheet.getRange(outputRows.length + 4, 1).setValue(
      "The link covers the first " + urlStops.length + " stops; Google Maps links allow at most " +
      CONFIG.MAX_URL_WAYPOINTS + " waypoints."
    );
  }
}
