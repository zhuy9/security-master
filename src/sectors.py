"""SIC code -> sector: this project's own mapping of SEC Standard Industrial Classification codes to
11 sectors plus "Other". It is not GICS or any other vendor scheme.

SIC is the only industry code the SEC publishes per issuer, and it is coarse: one code can hold a
test-equipment maker, a software company and a defence contractor. Expect misses where the filing
code is a catch-all: Accenture and Akamai file under 7389 and land in Financials.

The table follows SIC's own hierarchy, so it is read most-specific-first, like the code itself:

    3571  industry       (4 digits)  Electronic Computers
    357   industry group (3 digits)  Computer & Office Equipment
    35    major group    (2 digits)  Industrial Machinery & Equipment

Put an entry at the coarsest level that is right. A 4-digit exception names the companies that
justify it.
"""

# 4-digit industry. Exceptions to the group or major group above them.
BY_INDUSTRY: dict[int, str] = {
    1400: "Materials",  # nonmetallic mineral mining, not energy: MLM, VMC
    3021: "Consumer Discretionary",  # rubber footwear: NKE, DECK
    3420: "Industrials",  # handtools and hardware: SNA, SWK
    3663: "Technology",  # broadcast and comms equipment: QCOM, MSI
    3825: "Technology",  # electrical measuring and test: AEHR, FEIM
    3826: "Health Care",  # laboratory analytical instruments -- life-science tools: A
    3827: "Technology",  # optical instruments and lenses: COHR, KLAC
    3829: "Technology",  # measuring and controlling devices NEC: ONTO
    4400: "Consumer Discretionary",  # water transport is cruise lines: CCL, RCL, NCLH
    4700: "Consumer Discretionary",  # transport services is online travel: BKNG, EXPE
    4922: "Energy & Mining",  # gas transmission is a pipeline, not a utility: KMI, WMB, TRGP
    4953: "Industrials",  # refuse systems: WM, RSG
    5122: "Health Care",  # drug wholesale: MCK, CAH, COR
    5331: "Consumer Staples",  # variety stores: WMT, COST, TGT, DG, DLTR
    6324: "Health Care",  # hospital and medical service plans: UNH, ELV, CI, CNC, HUM
    6798: "Real Estate",  # REITs: PLD, AMT, EQIX, O
    7320: "Financials",  # credit reporting and ratings: SPGI, MCO
    7370: "Communication",  # the group says Technology; the big names here are media: GOOG, META
    # 7389 "Business Services, NEC" is a catch-all; the payment networks file here (Visa, Mastercard,
    # PayPal, FIS, Fiserv, Global Payments). Accenture and Akamai land here too and stay wrong.
    7389: "Financials",
    7900: "Communication",  # amusement and recreation: LYV, TKO
    8731: "Health Care",  # commercial biological research: IQV, CRL, INCY
}

# 3-digit industry group.
BY_GROUP: dict[int, str] = {
    152: "Consumer Discretionary",  # residential builders: LEN
    153: "Consumer Discretionary",  # operative builders: DHI, NVR, PHM
    283: "Health Care",  # drugs and biological products
    284: "Consumer Staples",  # soap, detergents, cosmetics: PG, CL, KMB
    357: "Technology",  # computer and office equipment
    367: "Technology",  # electronic components and semiconductors
    368: "Technology",
    369: "Technology",
    # 38 is "instruments" in general, not medical devices, so it splits three ways: 380-382 is
    # industrial and defence (L3Harris, Ametek, Trane) and falls through to 38 below, 383 optical
    # (Coherent, KLA), 384-385 medical. The 4-digit table above carves 3825 and 3826 back out of 382.
    383: "Technology",  # optical and photographic instruments
    384: "Health Care",  # surgical, orthopedic, dental, x-ray, electromedical
    385: "Health Care",  # ophthalmic goods: ALC, BLCO, COO
    386: "Consumer Discretionary",  # photographic equipment: KODK, IMAX
    372: "Industrials",  # aircraft and parts: HON, RTX, TXT
    373: "Industrials",  # ship and boat building: GD, HII
    737: "Technology",  # computer programming and data processing
}

# 2-digit major group -- the default for everything not named above.
BY_MAJOR: dict[int, str] = {
    10: "Energy & Mining", 12: "Energy & Mining", 13: "Energy & Mining", 14: "Energy & Mining",
    15: "Industrials", 16: "Industrials", 17: "Industrials",  # construction
    20: "Consumer Staples", 21: "Consumer Staples",  # food, tobacco
    22: "Consumer Discretionary", 23: "Consumer Discretionary", 24: "Consumer Discretionary",
    25: "Consumer Discretionary",  # textiles, apparel, lumber, furniture
    26: "Materials", 27: "Communication",  # paper; printing and publishing
    28: "Materials",  # chemicals -- 283 carved out above
    29: "Energy & Mining",  # petroleum refining
    30: "Materials", 31: "Materials", 32: "Materials", 33: "Materials", 34: "Materials",
    35: "Industrials", 36: "Industrials",  # machinery; electronics -- 357, 367-369 carved out
    37: "Consumer Discretionary",  # transportation equipment -- 372/373 carved out
    38: "Industrials",  # instruments -- see the 380-385 block above
    39: "Consumer Discretionary",  # misc manufacturing
    40: "Industrials", 41: "Industrials", 42: "Industrials", 43: "Industrials",
    44: "Industrials", 45: "Industrials", 46: "Industrials", 47: "Industrials",  # transport
    48: "Communication", 49: "Utilities",
    50: "Consumer Discretionary", 51: "Consumer Discretionary", 52: "Consumer Discretionary",
    53: "Consumer Discretionary", 54: "Consumer Discretionary", 55: "Consumer Discretionary",
    56: "Consumer Discretionary", 57: "Consumer Discretionary", 58: "Consumer Discretionary",
    59: "Consumer Discretionary",  # wholesale and retail trade
    60: "Financials", 61: "Financials", 62: "Financials", 63: "Financials", 64: "Financials",  # 6324 carved out
    65: "Real Estate",  # real estate operators and developers: CBRE, INVH
    66: "Financials", 67: "Financials",
    70: "Consumer Discretionary", 72: "Consumer Discretionary", 73: "Consumer Discretionary",
    75: "Consumer Discretionary", 76: "Consumer Discretionary", 78: "Consumer Discretionary",
    79: "Consumer Discretionary",  # services
    80: "Health Care",
    81: "Industrials", 82: "Industrials", 83: "Industrials", 84: "Industrials",
    86: "Industrials", 87: "Industrials", 89: "Industrials",
}  # fmt: skip


def sic_to_sector(sic: int) -> str:
    """Most specific match wins: industry, then industry group, then major group."""
    return BY_INDUSTRY.get(sic) or BY_GROUP.get(sic // 10) or BY_MAJOR.get(sic // 100) or "Other"
