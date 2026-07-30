# F001 – Master Data Generator

**Feature ID:** F001

**Feature Name:** Master Data Generator

**Priority:** Critical

**Status:** Ready for Implementation

**Version:** 1.0

**Owner:** Enterprise Architect

---

# 1. Purpose

The Enterprise Data Simulator (EDS) generates realistic enterprise datasets that closely resemble data found in production systems.

Every transactional system depends on a set of stable reference data known as **Master Data**.

This feature is responsible for generating all master data required before any transactional simulation begins.

No customer activities, orders, payments, shipments, or business events are generated in this feature.

The output of this feature becomes the foundation for all future simulation modules.

---

# 2. Business Objective

Generate a complete enterprise catalog containing realistic reference data that can support millions of business transactions.

The generated data must satisfy the following requirements:

- Internally consistent
- Referentially correct
- Deterministic when using the same random seed
- Configurable
- Realistic enough for analytics, AI, Spark, Databricks, Microsoft Fabric, SQL Server, Snowflake and Power BI demonstrations.

---

# 3. Why This Feature Exists

Every enterprise system contains two major categories of data.

## Master Data

Master data changes infrequently.

Examples include:

- Products
- Categories
- Brands
- Suppliers
- Warehouses
- Countries
- States
- Cities
- Shipping Methods
- Payment Methods
- Tax Codes

Master data acts as the foundation for all transactional data.

---

## Transaction Data

Transaction data changes continuously.

Examples include:

- Customer registrations
- Orders
- Payments
- Inventory movements
- Returns
- Reviews
- Deliveries

Transaction data references master data through foreign keys.

Therefore master data must exist before any transaction simulation can begin.

---

# 4. Scope

This feature is responsible for generating only enterprise reference datasets.

The following entities are included.

## Geography

- Countries
- States
- Cities
- Postal Codes

---

## Product Catalog

- Categories
- Sub Categories
- Brands
- Products

---

## Supply Chain

- Suppliers
- Warehouses
- Inventory

---

## Commercial

- Payment Methods
- Shipping Methods
- Tax Codes
- Coupon Types

---

## System Reference

- Currency
- Units of Measure
- Product Status
- Warehouse Status

---

# 5. Out of Scope

The following are NOT part of this feature.

- Customers
- Customer Addresses
- Customer Preferences
- Browsing Sessions
- Product Views
- Search History
- Shopping Carts
- Orders
- Payments
- Shipments
- Returns
- Reviews
- Business Events

These will be implemented in later features.

---

# 6. Business Assumptions

The simulator represents a large omni-channel retail enterprise.

Characteristics:

- Multiple warehouses
- Multiple suppliers
- Thousands of products
- Nationwide operations
- Online sales
- Mobile applications
- Physical inventory
- Multiple shipping providers

This simulator is not intended to represent a specific retailer.

Instead it should resemble a realistic combination of Amazon, Walmart, Target, Flipkart, and similar enterprise retailers.

---

# 7. Design Principles

The generated master data should satisfy the following principles.

## Realistic

Products should resemble real commercial products.

Prices should follow logical distributions.

Warehouses should have realistic capacities.

Cities should belong to valid states.

States should belong to valid countries.

---

## Scalable

The simulator should support datasets ranging from

- 100 products

to

- 100 million products

without requiring code changes.

---

## Configurable

Users should be able to configure

- Product count
- Warehouse count
- Supplier count
- Category depth
- Geographic regions
- Random seed

through configuration files or CLI parameters.

---

## Deterministic

Using the same random seed must generate identical datasets.

This is essential for

- Testing
- Benchmarking
- Regression testing
- Reproducible demos

---

## Extensible

Future domains such as

- Healthcare
- Banking
- Insurance
- Manufacturing

should be able to reuse the same architectural approach.

---

# 8. Dependencies

Required

F000 Repository Foundation

Future Dependencies

F002 Customer Generator

F003 Customer Behaviour Simulator

F004 Shopping Cart Simulator

F005 Order Simulator

F006 Payment Simulator

---

# 9. Outputs

The feature will generate the following datasets.

- countries.parquet
- states.parquet
- cities.parquet
- categories.parquet
- brands.parquet
- suppliers.parquet
- products.parquet
- warehouses.parquet
- inventory.parquet
- shipping_methods.parquet
- payment_methods.parquet
- tax_codes.parquet
- coupon_types.parquet

---

# 10. Success Criteria

This feature is considered complete when

- All master datasets are generated successfully
- Referential integrity is maintained
- No orphan records exist
- Output is deterministic using the same seed
- Parquet files are successfully exported
- Data is validated without errors

---

# 11. Future Relationship

This feature provides the foundation for every remaining feature in the simulator.

Future modules must never generate master data independently.

Instead they must consume the datasets generated by this feature.

Master Data Generator

↓

Customer Generator

↓

Browsing Simulator

↓

Shopping Cart Simulator

↓

Order Simulator

↓

Payment Simulator

↓

Shipment Simulator

↓

Returns Simulator

↓

Analytics Dataset Generator
