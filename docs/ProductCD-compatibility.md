# SecureCart and IEEE-CIS `ProductCD` compatibility

## Finding

No SecureCart catalog category can currently be mapped safely to an IEEE-CIS `ProductCD` value. The IEEE-CIS competition data description calls `ProductCD` a categorical transaction feature. It does not define the real-world meaning of the codes. The competition discussion likewise describes W, C, R, H, and S as separate product labels without disclosing a code-to-product dictionary. The source data provider's codebook or a verified crosswalk is not present in this repository.

Local inspection of `data/train_transaction.csv` found these values and counts:

| IEEE-CIS code | Training rows | Meaning established by available source material |
| --- | ---: | --- |
| W | 439,670 | Product code; specific product meaning undisclosed |
| C | 68,519 | Product code; specific product meaning undisclosed |
| R | 37,699 | Product code; specific product meaning undisclosed |
| H | 33,024 | Product code; specific product meaning undisclosed |
| S | 11,628 | Product code; specific product meaning undisclosed |

The saved GraphSAGE `ProductCD` encoder contains these five training labels and `UNKNOWN`. Encoder membership shows that a value occurred in training; it does not establish its business meaning. `UNKNOWN` is a sentinel, not an alternate supported product class.

## Storefront category decisions

| SecureCart category | Proposed IEEE-CIS code | Evidence and ambiguity | Confidence / safe for inference? |
| --- | --- | --- | --- |
| Audio | None | Catalog has headphones and a speaker. IEEE-CIS exposes opaque product codes and no category dictionary. | High confidence that current evidence is insufficient; unsafe to map |
| Wearables | None | Catalog lists a fitness tracker; no code semantics or crosswalk. | High confidence that current evidence is insufficient; unsafe to map |
| Accessories | None | Catalog lists a keyboard; no code semantics or crosswalk. | High confidence that current evidence is insufficient; unsafe to map |
| Bags | None | Catalog lists a backpack; no code semantics or crosswalk. | High confidence that current evidence is insufficient; unsafe to map |
| Home | None | Catalog combines a desk lamp and travel mug; no code semantics or crosswalk. | High confidence that current evidence is insufficient; unsafe to map |
| Footwear | None | Catalog lists running shoes; no code semantics or crosswalk. | High confidence that current evidence is insufficient; unsafe to map |

No category is assigned W, C, R, H, or S. No common/default code is used. The checkout path continues to store `ProductCD="UNKNOWN"` for catalog orders, retain the model score, and route the transaction to administrator review under the existing safeguard.

## Evidence needed to revisit this decision

Obtain an authoritative Vesta/IEEE-CIS dictionary that explains each code, or a product-level crosswalk approved by the data owner that connects the SecureCart product identifiers and product definitions to the source transactions. Then validate that the mapped values have the same meaning and scope as the training feature. A matching English category name, product type guess, encoder label, or fraud-rate association is not enough evidence.

## Sources

- [IEEE-CIS Fraud Detection competition data description](https://www.kaggle.com/c/ieee-fraud-detection/data) identifies `ProductCD` as a categorical transaction field but supplies no code-to-product mapping.
- [IEEE-CIS competition discussion on ProductCD](https://www.kaggle.com/c/ieee-fraud-detection/discussion/100002) describes W, C, R, H, and S as distinct product labels but does not disclose what each one represents.
