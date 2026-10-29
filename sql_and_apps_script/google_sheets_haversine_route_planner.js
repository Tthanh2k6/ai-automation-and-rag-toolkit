/**
 * ============================================================================
 * TROY — KANSAS CITY PROPERTY LEADS SMART ROUTE PLANNER (GOOGLE APPS SCRIPT)
 * ============================================================================
 * Built specifically for Troy's 104-row Kansas City sheet structure:
 * - Col A (Idx 0): Lead Status (Filters OUT "Under Contract" [5] & "Taken care of" [8];
 *                  prioritizes "Hot" [20], "JEWEL" [1], "For Verification" [2],
 *                  "Brayden's working on it" [12], "New" [4], and "In Progress" [48]).
 * - Col B (Idx 1): Owner Name
 * - Col C (Idx 2): Phone
 * - Col F (Idx 5): Property Address (Jackson, Clay, Johnson, Wyandotte, Platte)
 * - Col G (Idx 6): Contacted?
 * - Col H (Idx 7): County
 * - Col K (Idx 10): Occupied or Vacant
 * - Col N (Idx 13): Equity
 * - Col O (Idx 14): Comment / Lead Notes
 * - Col P (Idx 15): Visited Status & Last Visited Timestamp (Auto-tracked)
 */

const CONFIG = {
  LEADS_SHEET_NAME: "Sheet1",
  PLANNER_SHEET_NAME: "Route_Planner_Dashboard",
  PRINT_SHEET_NAME: "Printable_Route_Sheet",
  MINUTES_PER_STOP: 12, // Configurable dwell time at each property
  MAX_WAYPOINTS: 23,    // Google Maps Directions API waypoint ceiling per leg
  SKIP_STATUSES: ["under contract", "taken care of", "visited", "dead"],
  PRIORITY_WEIGHTS: {
    "jewel": 100,
    "hot": 90,
    "for verification": 80,
    "scheduled appt": 75,
    "new": 70,
    "brayden's working on it": 60,
    "in progress": 50,
    "bid at auction": 40
  }
};

/**
 * Adds a 1-click menu inside Google Sheets on open.
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚗 KC Smart Route Planner")
    .addItem("1. Setup Route Planner Inputs", "setupPlannerTabs")
    .addItem("2. Build Optimized Driving Route", "generateSmartPropertyRoute")
    .addItem("3. Mark Completed Stops as Visited", "markCheckedStopsVisited")
    .addToUi();
}

/**
 * Main Engine: Reads Start/End/Available Hours, scores unvisited KC leads,
 * packs the highest-value cluster within the time budget, calls native
 * Maps.newDirectionFinder() with optimizeWaypoints(true), and builds the
 * Printable Route Sheet + clickable Google Maps navigation link.
 */
function generateSmartPropertyRoute() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const leadsSheet = ss.getSheets()[0];
  const plannerSheet = ss.getSheetByName(CONFIG.PLANNER_SHEET_NAME) || setupPlannerTabs();
  const printSheet = ss.getSheetByName(CONFIG.PRINT_SHEET_NAME) || ss.insertSheet(CONFIG.PRINT_SHEET_NAME);

  // 1. Read user inputs from Planner Dashboard
  const startLocation = String(plannerSheet.getRange("B2").getValue() || "Downtown Kansas City, MO").trim();
  const endLocation = String(plannerSheet.getRange("B3").getValue() || startLocation).trim();
  const availableHours = parseFloat(plannerSheet.getRange("B4").getValue() || 2.0);
  const dwellMinutes = parseFloat(plannerSheet.getRange("B5").getValue() || CONFIG.MINUTES_PER_STOP);
  const countyFilter = String(plannerSheet.getRange("B6").getValue() || "ALL").trim().toUpperCase();

  const totalBudgetSeconds = Math.max(30, availableHours * 60) * 60;
  const dwellSecondsPerStop = dwellMinutes * 60;

  // 2. Load all 104+ rows from Troy's main property sheet
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
  const encodedWaypoints = finalStops.map(s => encodeURIComponent(s.prop.address)).join("|");
  const navUrl = "/maps/dir/?api=1&origin=" + encodedOrigin +
                 "&destination=" + encodedDest + "&travelmode=driving&waypoints=" + encodedWaypoints;

  // 7. Render Printable Route Sheet
  printSheet.clearContents();
  printSheet.getRange("A1:J1").setValues([[
    "Stop #", "Status", "Drive Mins", "Miles", "Property Address",
    "Owner Name", "Phone Number", "County / Occupancy", "Equity / Lead Notes", "Visited? (Check)"
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
    "FALSE"
  ]);

  if (outputRows.length > 0) {
    printSheet.getRange(2, 1, outputRows.length, 10).setValues(outputRows);
  }
  printSheet.getRange(outputRows.length + 3, 1).setValue("CLICK TO OPEN TURN-BY-TURN GOOGLE MAPS ROUTE:");
  printSheet.getRange(outputRows.length + 3, 2).setValue(navUrl);
}
