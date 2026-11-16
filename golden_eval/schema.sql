-- ColdChain Distribution schema (MySQL 8 / Aiven compatible)
-- A distributor of chilled and frozen goods to hospitals, pharmacies, restaurants and retail stores.
-- Every table has a primary key (Aiven MySQL enforces sql_require_primary_key by default).
-- Column COMMENTs are deliberate: feed them to the LLM with the schema; they act as a small semantic layer.

DROP TABLE IF EXISTS temperature_readings;
DROP TABLE IF EXISTS shipments;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS carriers;
DROP TABLE IF EXISTS warehouses;
DROP TABLE IF EXISTS regions;

CREATE TABLE regions (
  region_id   INT PRIMARY KEY,
  name        VARCHAR(40) NOT NULL COMMENT 'Region name: North, West, South, East, Northeast'
) COMMENT 'Sales regions of India';

CREATE TABLE warehouses (
  warehouse_id   INT PRIMARY KEY,
  name           VARCHAR(80) NOT NULL,
  city           VARCHAR(40) NOT NULL,
  region_id      INT NOT NULL,
  capacity_units INT NOT NULL COMMENT 'Storage capacity in pallet units',
  FOREIGN KEY (region_id) REFERENCES regions(region_id)
) COMMENT 'Cold storage warehouses that fulfil orders';

CREATE TABLE carriers (
  carrier_id INT PRIMARY KEY,
  name       VARCHAR(60) NOT NULL,
  mode       ENUM('Road','Air','Rail') NOT NULL COMMENT 'Transport mode'
) COMMENT 'Logistics partners that move shipments';

CREATE TABLE products (
  product_id    INT PRIMARY KEY,
  sku           VARCHAR(20) NOT NULL UNIQUE,
  name          VARCHAR(120) NOT NULL,
  category      ENUM('Dairy','Vaccines','Frozen Food','Fresh Produce','Packaging') NOT NULL,
  unit_price    DECIMAL(10,2) NOT NULL COMMENT 'CURRENT list price in INR. For historical revenue use order_items.unit_price',
  requires_cold TINYINT(1) NOT NULL COMMENT '1 = must travel within min_temp_c..max_temp_c',
  min_temp_c    DECIMAL(5,1) NULL COMMENT 'Lowest allowed temperature in Celsius; NULL if not temperature controlled',
  max_temp_c    DECIMAL(5,1) NULL COMMENT 'Highest allowed temperature in Celsius; NULL if not temperature controlled',
  discontinued  TINYINT(1) NOT NULL DEFAULT 0
) COMMENT 'Product catalogue';

CREATE TABLE customers (
  customer_id INT PRIMARY KEY,
  name        VARCHAR(120) NOT NULL,
  email       VARCHAR(120) NOT NULL COMMENT 'PII',
  city        VARCHAR(40) NOT NULL COMMENT 'Official city names, e.g. Bengaluru (not Bangalore), Mumbai (not Bombay)',
  region_id   INT NOT NULL,
  segment     ENUM('Hospital','Pharmacy','Restaurant','Retail') NOT NULL,
  signup_date DATE NOT NULL,
  is_active   TINYINT(1) NOT NULL COMMENT '1 = active account',
  FOREIGN KEY (region_id) REFERENCES regions(region_id)
) COMMENT 'B2B customers';

CREATE TABLE employees (
  employee_id  INT PRIMARY KEY,
  full_name    VARCHAR(80) NOT NULL,
  role         VARCHAR(40) NOT NULL,
  warehouse_id INT NULL COMMENT 'NULL for head-office staff',
  manager_id   INT NULL COMMENT 'Self-reference to employees.employee_id; NULL for the top manager',
  salary_inr   INT NOT NULL COMMENT 'SENSITIVE: annual salary',
  hired_on     DATE NOT NULL,
  FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id),
  FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
) COMMENT 'SENSITIVE table: admin role only';

CREATE TABLE orders (
  order_id     INT PRIMARY KEY,
  customer_id  INT NOT NULL,
  warehouse_id INT NOT NULL COMMENT 'Fulfilling warehouse',
  order_date   DATETIME NOT NULL COMMENT 'Has a time part; filter months with >= first day AND < first day of next month',
  status       ENUM('placed','shipped','delivered','cancelled','returned') NOT NULL COMMENT 'British spelling: cancelled',
  discount_pct DECIMAL(4,1) NULL COMMENT 'NULL means no discount (treat as 0)',
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
  FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
) COMMENT 'Customer orders';

CREATE TABLE order_items (
  order_item_id INT PRIMARY KEY,
  order_id      INT NOT NULL,
  product_id    INT NOT NULL,
  quantity      INT NOT NULL,
  unit_price    DECIMAL(10,2) NOT NULL COMMENT 'Price at time of sale in INR (may differ from products.unit_price)',
  FOREIGN KEY (order_id) REFERENCES orders(order_id),
  FOREIGN KEY (product_id) REFERENCES products(product_id)
) COMMENT 'Order lines';

CREATE TABLE shipments (
  shipment_id   INT PRIMARY KEY,
  order_id      INT NOT NULL COMMENT 'An order can be split into more than one shipment',
  carrier_id    INT NOT NULL,
  shipped_at    DATETIME NOT NULL,
  promised_date DATE NOT NULL,
  delivered_at  DATETIME NULL COMMENT 'NULL = still in transit',
  freight_cost  DECIMAL(10,2) NOT NULL COMMENT 'INR',
  FOREIGN KEY (order_id) REFERENCES orders(order_id),
  FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id)
) COMMENT 'Physical shipments';

CREATE TABLE temperature_readings (
  reading_id  INT PRIMARY KEY,
  shipment_id INT NOT NULL,
  recorded_at DATETIME NOT NULL,
  temp_c      DECIMAL(5,1) NOT NULL,
  FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
) COMMENT 'In-transit temperature sensor readings for temperature-controlled shipments';

CREATE INDEX ix_orders_date ON orders(order_date);
CREATE INDEX ix_orders_customer ON orders(customer_id);
CREATE INDEX ix_items_order ON order_items(order_id);
CREATE INDEX ix_ship_order ON shipments(order_id);
CREATE INDEX ix_read_ship ON temperature_readings(shipment_id);
