-- Tiny fixture: 6 zones and 20 trips. The schema and payment_types come from asksql.schema.
-- Rows 17-20 are deliberately dirty.

INSERT INTO zones VALUES (1, 'EWR', 'Newark Airport', 'EWR');
INSERT INTO zones VALUES (132, 'Queens', 'JFK Airport', 'Airports');
INSERT INTO zones VALUES (138, 'Queens', 'LaGuardia Airport', 'Airports');
INSERT INTO zones VALUES (161, 'Manhattan', 'Midtown Center', 'Yellow Zone');
INSERT INTO zones VALUES (236, 'Manhattan', 'Upper East Side North', 'Yellow Zone');
INSERT INTO zones VALUES (181, 'Brooklyn', 'Park Slope', 'Boro Zone');

-- trip_id, vendor, pickup, dropoff, passengers, miles, rate, pu, do, payment, fare, tip, tolls, congestion, airport_fee, total
INSERT INTO trips VALUES (1, 1, '2024-01-01 08:05:00', '2024-01-01 08:20:00', 1, 2.1, 1, 161, 236, 1, 12.0, 3.0, 0.0, 2.5, 0.0, 19.0);
INSERT INTO trips VALUES (2, 2, '2024-01-01 09:10:00', '2024-01-01 09:55:00', 2, 17.3, 2, 132, 161, 1, 70.0, 15.0, 6.94, 2.5, 1.75, 97.69);
INSERT INTO trips VALUES (3, 2, '2024-01-02 18:30:00', '2024-01-02 18:42:00', 1, 1.4, 1, 236, 161, 2, 9.5, 0.0, 0.0, 2.5, 0.0, 13.5);
INSERT INTO trips VALUES (4, 1, '2024-01-03 23:15:00', '2024-01-03 23:50:00', 3, 9.8, 1, 138, 181, 1, 38.0, 8.0, 0.0, 0.0, 1.75, 49.25);
INSERT INTO trips VALUES (5, 2, '2024-01-04 07:45:00', '2024-01-04 08:00:00', 1, 2.6, 1, 161, 161, 1, 13.5, 2.5, 0.0, 2.5, 0.0, 20.0);
INSERT INTO trips VALUES (6, 2, '2024-01-05 12:00:00', '2024-01-05 12:25:00', 1, 4.2, 1, 236, 181, 2, 21.0, 0.0, 0.0, 2.5, 0.0, 25.0);
INSERT INTO trips VALUES (7, 1, '2024-01-06 14:20:00', '2024-01-06 14:35:00', 2, 1.9, 1, 161, 236, 1, 11.0, 2.0, 0.0, 2.5, 0.0, 17.0);
INSERT INTO trips VALUES (8, 2, '2024-01-06 20:05:00', '2024-01-06 20:50:00', 1, 16.9, 2, 161, 132, 1, 70.0, 10.0, 6.94, 2.5, 0.0, 90.94);
INSERT INTO trips VALUES (9, 2, '2024-01-07 10:10:00', '2024-01-07 10:22:00', 1, 1.2, 1, 181, 181, 2, 8.0, 0.0, 0.0, 0.0, 0.0, 9.5);
INSERT INTO trips VALUES (10, 1, '2024-01-08 08:40:00', '2024-01-08 09:05:00', 1, 3.3, 1, 236, 161, 1, 18.5, 4.0, 0.0, 2.5, 0.0, 26.5);
INSERT INTO trips VALUES (11, 2, '2024-01-09 17:55:00', '2024-01-09 18:30:00', 4, 8.7, 1, 138, 161, 1, 36.0, 7.5, 6.94, 2.5, 1.75, 56.19);
INSERT INTO trips VALUES (12, 2, '2024-01-10 06:30:00', '2024-01-10 07:05:00', 1, 16.5, 3, 161, 1, 1, 85.0, 12.0, 14.75, 2.5, 0.0, 115.75);
INSERT INTO trips VALUES (13, 1, '2024-01-11 13:00:00', '2024-01-11 13:09:00', 5, 0.9, 1, 161, 161, 2, 7.0, 0.0, 0.0, 2.5, 0.0, 11.0);
INSERT INTO trips VALUES (14, 2, '2024-01-12 22:10:00', '2024-01-12 22:28:00', 2, 3.0, 1, 181, 236, 1, 16.0, 3.5, 0.0, 2.5, 0.0, 23.5);
INSERT INTO trips VALUES (15, 2, '2024-01-13 01:20:00', '2024-01-13 01:38:00', 1, 3.8, 1, 236, 236, 3, 17.0, 0.0, 0.0, 2.5, 0.0, 21.0);
INSERT INTO trips VALUES (16, 6, '2024-01-14 11:00:00', '2024-01-14 13:30:00', NULL, 25.0, NULL, 132, 181, 0, 60.0, 0.0, 0.0, NULL, NULL, 61.5);
INSERT INTO trips VALUES (17, 2, '2024-01-15 09:00:00', '2024-01-15 09:10:00', 1, 1.5, 1, 161, 236, 4, -10.0, 0.0, 0.0, -2.5, 0.0, -14.0);
INSERT INTO trips VALUES (18, 1, '2024-01-16 15:00:00', '2024-01-16 15:20:00', 0, 0.0, 1, 236, 236, 2, 14.0, 0.0, 0.0, 2.5, 0.0, 18.0);
INSERT INTO trips VALUES (19, 2, '2024-01-17 19:30:00', '2024-01-17 19:10:00', 1, 2.0, 1, 161, 181, 1, 12.0, 2.0, 0.0, 2.5, 0.0, 18.0);
INSERT INTO trips VALUES (20, 2, '2009-01-01 00:15:00', '2009-01-01 00:30:00', 1, 2.4, 1, 181, 161, 1, 13.0, 2.6, 0.0, 2.5, 0.0, 19.6);
