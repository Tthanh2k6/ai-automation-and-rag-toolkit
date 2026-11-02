"""
Odoo ERP to Power BI Inventory Connector and Power Query M Generator
Covers two common integration methods:
  1. PostgreSQL SQL views on a read replica (Power BI connects to them directly)
  2. Power Query M calling Odoo JSON-RPC, with Web.Contents + RelativePath so the
     Power BI Service can schedule a refresh

Column names follow Odoo 17 (stock_move.quantity, jsonb product_template.name).
Odoo 16 uses stock_move.quantity_done; Odoo 15 and older also store
product_template.name as plain text, so adjust those two lines for older versions.
Not tested against a live Odoo database.

Run `python odoo_erp_to_powerbi_connector.py` to print both scripts.
"""

ODOO_POSTGRES_INVENTORY_SQL_VIEWS = """
-- 1. Dim_Products_SKUs (Maps Odoo product_product + product_template to Power BI SKU table)
CREATE OR REPLACE VIEW pbi_dim_products_skus AS
SELECT
    pp.id AS product_id,
    COALESCE(pp.default_code, 'NO-SKU-' || pp.id::text) AS sku_code,
    pt.name->>'en_US' AS product_name,
    pc.complete_name AS product_category,
    pp.barcode,
    pp.active
FROM product_product pp
JOIN product_template pt ON pp.product_tmpl_id = pt.id
LEFT JOIN product_category pc ON pt.categ_id = pc.id;

-- 2. Fact_Inventory_OnHand (Maps stock_quant filtered to internal warehouse locations)
CREATE OR REPLACE VIEW pbi_fact_inventory_onhand AS
SELECT
    sq.id AS quant_id,
    sq.product_id,
    sq.location_id,
    sl.warehouse_id,
    sq.quantity AS on_hand_qty,
    sq.reserved_quantity AS reserved_qty,
    (sq.quantity - sq.reserved_quantity) AS available_qty,
    sq.write_date AS last_updated_utc
FROM stock_quant sq
JOIN stock_location sl ON sq.location_id = sl.id
WHERE sl.usage = 'internal';

-- 3. Fact_Stock_Moves (Maps stock_move for historical inventory movement and turnover DAX)
CREATE OR REPLACE VIEW pbi_fact_stock_moves AS
SELECT
    sm.id AS move_id,
    sm.product_id,
    sm.product_uom_qty,
    sm.quantity AS quantity_done,
    sm.location_id AS source_location_id,
    sm.location_dest_id AS dest_location_id,
    sm.state,
    sm.date AS move_date_utc
FROM stock_move sm
WHERE sm.state = 'done';
"""

POWER_QUERY_M_ODOO_JSONRPC_SCRIPT = """
// Power Query M script. A static BaseUrl plus RelativePath keeps the query refreshable in the
// Power BI Service (it rejects data sources built from dynamic URL strings).
// Replace the BaseUrl, database name, user id (2) and API key placeholders.
let
    BaseUrl = "https://your-odoo-instance.example.com",
    FetchBatch = (Offset as number) =>
        let
            Payload = Json.FromValue([
                jsonrpc = "2.0",
                method = "call",
                params = [
                    service = "object",
                    method = "execute_kw",
                    args = {
                        "odoo_db_name", 2, "api_key_placeholder",
                        "stock.quant", "search_read",
                        {{{"location_id.usage", "=", "internal"}}},
                        [
                            fields = {"product_id", "location_id", "quantity", "reserved_quantity", "write_date"},
                            limit = 2000,
                            offset = Offset
                        ]
                    }
                ],
                id = 1
            ]),
            Response = Json.Document(
                Web.Contents(
                    BaseUrl,
                    [
                        RelativePath = "jsonrpc",
                        Headers = [#"Content-Type" = "application/json"],
                        Content = Payload
                    ]
                )
            ),
            Records = Response[result]
        in
            Records
in
    FetchBatch(0)
"""

if __name__ == "__main__":
    print("-- PostgreSQL views for Power BI --")
    print(ODOO_POSTGRES_INVENTORY_SQL_VIEWS)
    print("// Power Query M (Odoo JSON-RPC) --")
    print(POWER_QUERY_M_ODOO_JSONRPC_SCRIPT)
