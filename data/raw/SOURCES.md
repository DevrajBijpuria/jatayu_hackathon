# Corpus Sources

## RBI Circulars (`data/raw/rbi/`)

The RBI files are inspired by the actual demonetisation-era cash withdrawal limit
circulars issued by the Reserve Bank of India in 2016-17. The document IDs and content
have been simplified and adapted for benchmark use.

| File | Inspired by | Public Source |
|------|-------------|---------------|
| `rbi-dcc-2017-01.txt` | RBI/2016-17/260 (30 Jan 2017) — Rs. 24,000/week limit circular | https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=10814 |
| `rbi-dcc-2017-02.txt` | RBI/2016-17/427 (20 Feb 2017) — Rs. 50,000/week revision | https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=10869 |
| `rbi-dcc-2017-03.txt` | RBI/2016-17/552 (13 Mar 2017) — Removal of restrictions | https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=10907 |

**Note**: The Rs. 10,000 initial limit in `rbi-dcc-2017-01.txt` reflects the
November 2016 initial restrictions (RBI/2016-17/173); the chain is compressed
into three files for benchmark purposes.

RBI Master Circulars index: https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx

## EPFO Circulars (`data/raw/epfo/`)

The EPFO files reflect the two wage ceiling notifications issued under the
Employees' Provident Funds and Miscellaneous Provisions Act, 1952.

| File | Inspired by | Public Source |
|------|-------------|---------------|
| `epfo-ro-2001.txt` | EPF wage ceiling at Rs. 6,500/month (pre-2014) | https://www.epfindia.gov.in/site_en/FAQ.php |
| `epfo-ro-2014.txt` | GSR 598(E) dated 22 Aug 2014 — Rs. 15,000 ceiling | https://labour.gov.in/sites/default/files/GSR598(E)22August2014.pdf |

EPFO circulars index: https://www.epfindia.gov.in/site_en/Circulars.php

## Acme Corpus (`data/raw/acme/`)

Synthetic documents. No external sources.
