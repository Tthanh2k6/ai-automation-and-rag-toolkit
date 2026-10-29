"""
Pedro - Odoo ERP to Power BI Inventory Connector and Power Query M Generator
Covers both integration methods requested in the scope:
  1. Direct PostgreSQL Read-Replica SQL Views (Fastest for Power BI Scheduled Refresh)
  2. Power Query M (Odoo JSON-RPC / REST API using Web.Contents RelativePath for Power BI Service)
"""

ODOO_POSTGRES_INVENTORY_SQL_VIEWS = """
-- 1. Dim_Products_SKUs (Maps Odoo product_product + product_template to Power BI SKU table)
CREATE OR REPLACE VIEW pbi_dim_products_skus AS
SELECT
    pp_id AS product_id,
    COALESCE(pp.default_code, 'NO-SKU-' || pp_id::text) AS sku_code,
    pt.name->>'en_US' AS product_name,
    pc.complete_name AS product_category,
    pp.barcode,
    pp.active
FROM product_product pp
JOIN product_template pt ON pp.product_tmpl_id = pt_id
LEFT JOIN product_category pc ON pt.categ_id = pc_id;

-- 2. Fact_Inventory_OnHand (Maps stock_quant filtered to internal warehouse locations)
CREATE OR REPLACE VIEW pbi_fact_inventory_onhand AS
SELECT
    sq_id AS quant_id,
    sq.product_id,
    sq.location_id,
    sl.warehouse_id,
    sq.quantity AS on_hand_qty,
    sq.reserved_quantity AS reserved_qty,
    (sq.quantity - sq.reserved_quantity) AS available_qty,
    sq.write_date AS last_updated_utc
FROM stock_quant sq
JOIN stock_location sl ON sq.location_id = sl_id
WHERE sl.usage = 'internal';

-- 3. Fact_Stock_Moves (Maps stock_move for historical inventory movement and turnover DAX)
CREATE OR REPLACE VIEW pbi_fact_stock_moves AS
SELECT
    sm_id AS move_id,
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
// Power Query M Script using Web.Contents RelativePath so Power BI Service Scheduled Refresh NEVER fails
let
    BaseUrl = "your-odoo-instance-placeholder",
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
    print("Odoo -> Power BI SQL Views and Power Query M Script ready for Pedro.")
