# Dataset names by domain

Extracted directly from the dataset-reference tables in each ER diagram file.

---

## Healthcare domain — 35 datasets

### Master data (12)
1. countries
2. states
3. cities
4. departments
5. specialties
6. insurance_plans
7. room_types
8. medications
9. diagnosis_codes
10. procedure_codes
11. billing_codes
12. facilities

### Patients (4)
13. patients
14. patient_addresses
15. patient_insurance
16. patient_allergies

### Providers (3)
17. providers
18. provider_departments
19. provider_specialties

### Encounters (6)
20. encounters
21. appointments
22. vitals
23. medications_prescribed
24. diagnoses
25. procedures

### Billing (2)
26. billing
27. claims

### Additional (8)
28. lab_results
29. radiology_reports
30. medication_administration
31. admissions
32. discharge_summaries
33. immunizations
34. referrals
35. patient_emergency_contacts

---

## Retail domain — 39 datasets

### Master data (14)
1. countries
2. states
3. cities
4. payment_methods
5. shipping_methods
6. tax_codes
7. coupon_types
8. return_reasons
9. suppliers
10. warehouses
11. categories
12. brands
13. products
14. inventory

### Customer (4)
15. customers
16. customer_addresses
17. customer_preferences
18. customer_loyalty

### Journey (2)
19. customer_personas
20. sessions

### Browsing (2)
21. category_views
22. search_history

### Engagement (2)
23. product_views
24. wishlists

### Commerce (2)
25. shopping_carts
26. cart_items

### Checkout (1)
27. checkout

### Orders (3)
28. orders
29. order_lines
30. order_status_history

### Payments (2)
31. payments
32. payment_status_history

### Shipments (3)
33. shipments
34. shipment_items
35. shipment_status_history

### Returns (3)
36. returns
37. return_items
38. return_status_history

### Reviews (1)
39. reviews

---

## Note on counts

The retail source file's own summary line stated "Total: 34 datasets," but counting the
actual rows in its dataset-reference tables gives 39. This file lists what is actually
present in the tables (35 healthcare + 39 retail = 74 datasets total), not the stated
summary figure.
