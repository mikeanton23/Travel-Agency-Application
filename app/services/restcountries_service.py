# -*- coding: utf-8 -*-

import requests


REST_COUNTRIES_URL = (
    "https://restcountries.com/api/v1/all"
)

REQUEST_TIMEOUT = 10

COUNTRIES_CACHE = None
CONTINENT_COUNTRIES_CACHE = None
COUNTRY_CONTINENT_CACHE = {}
COUNTRY_CODE_CACHE = {}
COUNTRY_NAME_CACHE = {}


FALLBACK_COUNTRIES = [
    {"name": "Greece", "cca2": "GR", "cca3": "GRC", "continent": "Europe", "region": "Europe", "subregion": "Southern Europe"},
    {"name": "Italy", "cca2": "IT", "cca3": "ITA", "continent": "Europe", "region": "Europe", "subregion": "Southern Europe"},
    {"name": "Spain", "cca2": "ES", "cca3": "ESP", "continent": "Europe", "region": "Europe", "subregion": "Southern Europe"},
    {"name": "Portugal", "cca2": "PT", "cca3": "PRT", "continent": "Europe", "region": "Europe", "subregion": "Southern Europe"},
    {"name": "France", "cca2": "FR", "cca3": "FRA", "continent": "Europe", "region": "Europe", "subregion": "Western Europe"},
    {"name": "Croatia", "cca2": "HR", "cca3": "HRV", "continent": "Europe", "region": "Europe", "subregion": "Southeast Europe"},
    {"name": "Cyprus", "cca2": "CY", "cca3": "CYP", "continent": "Europe", "region": "Europe", "subregion": "Southern Europe"},
    {"name": "Malta", "cca2": "MT", "cca3": "MLT", "continent": "Europe", "region": "Europe", "subregion": "Southern Europe"},
    {"name": "Albania", "cca2": "AL", "cca3": "ALB", "continent": "Europe", "region": "Europe", "subregion": "Southeast Europe"},
    {"name": "Montenegro", "cca2": "ME", "cca3": "MNE", "continent": "Europe", "region": "Europe", "subregion": "Southeast Europe"},
    {"name": "United Kingdom", "cca2": "GB", "cca3": "GBR", "continent": "Europe", "region": "Europe", "subregion": "Northern Europe"},
    {"name": "Turkey", "cca2": "TR", "cca3": "TUR", "continent": "Asia", "region": "Asia", "subregion": "Western Asia"},
    {"name": "Japan", "cca2": "JP", "cca3": "JPN", "continent": "Asia", "region": "Asia", "subregion": "Eastern Asia"},
    {"name": "Thailand", "cca2": "TH", "cca3": "THA", "continent": "Asia", "region": "Asia", "subregion": "South-Eastern Asia"},
    {"name": "Indonesia", "cca2": "ID", "cca3": "IDN", "continent": "Asia", "region": "Asia", "subregion": "South-Eastern Asia"},
    {"name": "Morocco", "cca2": "MA", "cca3": "MAR", "continent": "Africa", "region": "Africa", "subregion": "Northern Africa"},
    {"name": "Egypt", "cca2": "EG", "cca3": "EGY", "continent": "Africa", "region": "Africa", "subregion": "Northern Africa"},
    {"name": "United States", "cca2": "US", "cca3": "USA", "continent": "North America", "region": "Americas", "subregion": "North America"},
    {"name": "Canada", "cca2": "CA", "cca3": "CAN", "continent": "North America", "region": "Americas", "subregion": "North America"},
    {"name": "Mexico", "cca2": "MX", "cca3": "MEX", "continent": "North America", "region": "Americas", "subregion": "North America"},
    {"name": "Brazil", "cca2": "BR", "cca3": "BRA", "continent": "South America", "region": "Americas", "subregion": "South America"},
    {"name": "Argentina", "cca2": "AR", "cca3": "ARG", "continent": "South America", "region": "Americas", "subregion": "South America"},
    {"name": "Australia", "cca2": "AU", "cca3": "AUS", "continent": "Oceania", "region": "Oceania", "subregion": "Australia and New Zealand"},
    {"name": "New Zealand", "cca2": "NZ", "cca3": "NZL", "continent": "Oceania", "region": "Oceania", "subregion": "Australia and New Zealand"},
]


SUGGESTED_CITIES_BY_CONTINENT = {
    "Europe": [
        "Athens, Greece", "Santorini, Greece", "Chania, Greece", "Corfu, Greece",
        "Rome, Italy", "Florence, Italy", "Venice, Italy", "Amalfi Coast, Italy",
        "Barcelona, Spain", "Seville, Spain", "Lisbon, Portugal", "Porto, Portugal",
        "Paris, France", "Nice, France", "Dubrovnik, Croatia", "Kotor, Montenegro",
    ],
    "Asia": [
        "Tokyo, Japan", "Kyoto, Japan", "Osaka, Japan",
        "Bangkok, Thailand", "Chiang Mai, Thailand", "Phuket, Thailand",
        "Bali, Indonesia", "Ubud, Indonesia", "Istanbul, Turkey",
        "Cappadocia, Turkey", "Seoul, South Korea", "Singapore, Singapore",
    ],
    "Africa": [
        "Marrakesh, Morocco", "Fes, Morocco", "Casablanca, Morocco",
        "Cairo, Egypt", "Luxor, Egypt", "Cape Town, South Africa",
        "Zanzibar, Tanzania", "Nairobi, Kenya", "Tunis, Tunisia",
    ],
    "North America": [
        "New York, United States", "Los Angeles, United States", "San Francisco, United States",
        "Miami, United States", "Las Vegas, United States", "Vancouver, Canada",
        "Toronto, Canada", "Montreal, Canada", "Mexico City, Mexico", "Cancun, Mexico",
    ],
    "South America": [
        "Rio de Janeiro, Brazil", "Sao Paulo, Brazil", "Buenos Aires, Argentina",
        "Mendoza, Argentina", "Cusco, Peru", "Lima, Peru",
        "Santiago, Chile", "Cartagena, Colombia", "Medellin, Colombia",
    ],
    "Oceania": [
        "Sydney, Australia", "Melbourne, Australia", "Brisbane, Australia",
        "Perth, Australia", "Auckland, New Zealand", "Queenstown, New Zealand",
        "Wellington, New Zealand", "Fiji Islands, Fiji",
    ],
}


COUNTRY_ALIASES = {
    "greece": "Greece",
    "greek": "Greece",
    "hellas": "Greece",
    "ellada": "Greece",
    "e??ada": "Greece",
    "e???da": "Greece",
    "italy": "Italy",
    "italia": "Italy",
    "spain": "Spain",
    "espana": "Spain",
    "espana": "Spain",
    "france": "France",
    "croatia": "Croatia",
    "portugal": "Portugal",
    "cyprus": "Cyprus",
    "malta": "Malta",
    "turkey": "Turkey",
    "turkiye": "Turkey",
    "usa": "United States",
    "u.s.a.": "United States",
    "us": "United States",
    "u.s.": "United States",
    "america": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
}


def _normalize_key(value: str) -> str:
    return str(value or "").lower().strip()


def _reset_group_cache():
    global CONTINENT_COUNTRIES_CACHE
    CONTINENT_COUNTRIES_CACHE = None


def _add_country_to_cache(country: dict):
    name = country.get("name")
    continent = country.get("continent")
    cca2 = country.get("cca2")
    cca3 = country.get("cca3")

    if not name or not continent:
        return

    for key in [name, cca2, cca3]:
        normalized = _normalize_key(key)
        if normalized:
            COUNTRY_CONTINENT_CACHE[normalized] = continent
            COUNTRY_NAME_CACHE[normalized] = name

    if cca2:
        COUNTRY_CODE_CACHE[_normalize_key(name)] = str(cca2).upper()
        COUNTRY_CODE_CACHE[_normalize_key(cca2)] = str(cca2).upper()

    if cca3 and cca2:
        COUNTRY_CODE_CACHE[_normalize_key(cca3)] = str(cca2).upper()

    for alias, alias_country in COUNTRY_ALIASES.items():
        if alias_country == name:
            alias_key = _normalize_key(alias)
            COUNTRY_CONTINENT_CACHE[alias_key] = continent
            COUNTRY_NAME_CACHE[alias_key] = name

            if cca2:
                COUNTRY_CODE_CACHE[alias_key] = str(cca2).upper()


def _add_alt_names_to_cache(country: dict, raw_item: dict):
    name = country.get("name")
    continent = country.get("continent")
    cca2 = country.get("cca2")

    if not name or not continent:
        return

    for alt in raw_item.get("altSpellings", []) or []:
        key = _normalize_key(alt)
        if key:
            COUNTRY_CONTINENT_CACHE[key] = continent
            COUNTRY_NAME_CACHE[key] = name
            if cca2:
                COUNTRY_CODE_CACHE[key] = str(cca2).upper()

    translations = raw_item.get("translations", {}) or {}

    for translation in translations.values():
        if not isinstance(translation, dict):
            continue

        for field in ["common", "official"]:
            key = _normalize_key(translation.get(field))
            if key:
                COUNTRY_CONTINENT_CACHE[key] = continent
                COUNTRY_NAME_CACHE[key] = name
                if cca2:
                    COUNTRY_CODE_CACHE[key] = str(cca2).upper()


def _parse_rest_country(item):

    if not isinstance(item, dict):
        return None

    name = item.get("name")

    if not isinstance(name, dict):
        return None

    common_name = name.get("common")

    continents = item.get("continents", [])

    continent = (
        continents[0]
        if isinstance(continents, list) and continents
        else None
    )

    if not common_name or not continent:
        return None

    return {
        "name": common_name,
        "cca2": item.get("cca2"),
        "cca3": item.get("cca3"),
        "continent": continent,
        "region": item.get("region"),
        "subregion": item.get("subregion"),
    }


def _load_fallback_countries():
    global COUNTRIES_CACHE

    COUNTRY_CONTINENT_CACHE.clear()
    COUNTRY_CODE_CACHE.clear()
    COUNTRY_NAME_CACHE.clear()
    _reset_group_cache()

    countries = []

    for country in FALLBACK_COUNTRIES:
        countries.append(country)
        _add_country_to_cache(country)

    COUNTRIES_CACHE = sorted(countries, key=lambda c: c["name"])

    print(f"[REST COUNTRIES FALLBACK] Loaded {len(COUNTRIES_CACHE)} fallback countries")

    return COUNTRIES_CACHE


def load_all_countries(force_reload: bool = False):
    global COUNTRIES_CACHE

    if COUNTRIES_CACHE is not None and not force_reload:
        return COUNTRIES_CACHE

    # Use the local database instead of the deprecated API.
    return _load_fallback_countries()


def build_continent_countries():
    global CONTINENT_COUNTRIES_CACHE

    if CONTINENT_COUNTRIES_CACHE is not None:
        return CONTINENT_COUNTRIES_CACHE

    grouped = {}

    for country in load_all_countries():
        continent = country.get("continent")
        name = country.get("name")

        if continent and name:
            grouped.setdefault(continent, []).append(name)

    for continent in grouped:
        grouped[continent] = sorted(list(set(grouped[continent])))

    CONTINENT_COUNTRIES_CACHE = grouped

    return CONTINENT_COUNTRIES_CACHE


def get_available_continents():
    return sorted(build_continent_countries().keys())


def get_countries_by_continent(continent: str = "Any"):
    grouped = build_continent_countries()

    if not continent or continent == "Any":
        all_countries = []

        for countries in grouped.values():
            all_countries.extend(countries)

        return sorted(list(set(all_countries)))

    return grouped.get(continent, [])


def get_suggested_cities_by_continent(continent: str = "Any"):
    if not continent or continent == "Any":
        cities = []

        for values in SUGGESTED_CITIES_BY_CONTINENT.values():
            cities.extend(values)

        return sorted(list(dict.fromkeys(cities)))

    return SUGGESTED_CITIES_BY_CONTINENT.get(continent, [])


def normalize_country_name(country_name: str = ""):
    load_all_countries()

    key = _normalize_key(country_name)

    if not key:
        return None

    alias_country = COUNTRY_ALIASES.get(key)

    if alias_country:
        return alias_country

    return COUNTRY_NAME_CACHE.get(key)


def get_country_code(country_name: str = ""):
    load_all_countries()

    key = _normalize_key(country_name)

    if not key:
        return ""

    alias_country = COUNTRY_ALIASES.get(key)

    if alias_country:
        key = _normalize_key(alias_country)

    return str(COUNTRY_CODE_CACHE.get(key) or "").upper()


def get_country_continent(country_code: str = "", country_name: str = ""):
    load_all_countries()

    raw_key = country_code or country_name or ""
    key = _normalize_key(raw_key)

    if not key:
        return None

    alias_country = COUNTRY_ALIASES.get(key)

    if alias_country:
        key = _normalize_key(alias_country)

    return COUNTRY_CONTINENT_CACHE.get(key)


def country_belongs_to_continent(country_name: str = "", continent: str = "Any"):
    if not continent or continent == "Any":
        return True

    real_continent = get_country_continent(country_name=country_name)

    return real_continent == continent