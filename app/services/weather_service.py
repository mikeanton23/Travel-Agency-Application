"""
weather_service.py

Weather Service for Travel AI App

Features
--------
? Current weather
? Hourly forecast
? Daily forecast
? Geocoding
? Async requests
? Automatic retries
? Timeout handling
? Logging
? Dataclasses
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

def _check_api_key():

    if not OPENWEATHER_API_KEY:
        raise RuntimeError(
            "OPENWEATHER_API_KEY is missing from .env"
        )

def uv_risk_level(uv: float) -> str:

    if uv < 3:
        return "Low"

    if uv < 6:
        return "Moderate"

    if uv < 8:
        return "High"

    if uv < 11:
        return "Very High"

    return "Extreme"
    
def cloud_level(clouds: int) -> str:

    if clouds < 10:
        return "Clear"

    if clouds < 30:
        return "Mostly Sunny"

    if clouds < 60:
        return "Partly Cloudy"

    if clouds < 85:
        return "Mostly Cloudy"

    return "Overcast"
# ==========================================================
# CONFIG
# ==========================================================

from app.utils.config import OPENWEATHER_API_KEY

BASE_URL = "https://api.openweathermap.org"
TIMEOUT = 15


# ==========================================================
# DATA CLASSES
# ==========================================================

@dataclass
class CurrentWeather:

    city: str
    country: str

    temperature: float
    feels_like: float

    humidity: int
    pressure: int

    wind_speed: float

    description: str
    icon: str

    visibility: int
    sunrise: datetime
    sunset: datetime
    
    uv_index: float
    cloud_coverage: int
    
    rain_1h: float
    snow_1h: float


@dataclass
class DailyForecast:

    date: datetime

    temp_min: float
    temp_max: float

    humidity: int

    wind_speed: float

    description: str
    icon: str

    rain_probability: float
    
    cloud_coverage: int


@dataclass
class HourlyForecast:

    timestamp: datetime

    temperature: float

    humidity: int

    rain_probability: float
    
    cloud_coverage: int

    icon: str

    description: str
    
    rain_amount: float
    

class WeatherAlert:

    sender: str

    event: str

    start: datetime

    end: datetime

    description: str

    tags: list[str]
    
# ==========================================================
# WEATHER SERVICE
# ==========================================================

class WeatherService:
    """
    OpenWeather service.

    Features
    --------
    Current weather
    Hourly forecast
    Daily forecast
    Geocoding
    Automatic retries
    Timeout handling
    Session reuse
    """

    def __init__(self):

        if not OPENWEATHER_API_KEY:
            raise RuntimeError(
                "OPENWEATHER_API_KEY not found in .env"
            )
    
        self.timeout = aiohttp.ClientTimeout(
            total=TIMEOUT,
        )
    
        self.session = aiohttp.ClientSession(
            timeout=self.timeout,
        )
        
        self.VALID_UNITS = {
            "metric",
            "imperial",
            "standard",
        }
    
        # --------------------------------------
        # Cache
        # --------------------------------------
    
        self.geo_cache = {}
        self.forecast_cache = {}
    
        # seconds
        self.geo_cache_ttl = 86400      # 24 hours
        self.forecast_cache_ttl = 600   # 10 minutes

    # ------------------------------------------------------

    async def close(self):

        """
        Close HTTP session.
        """

        if not self.session.closed:
            await self.session.close()

    # ------------------------------------------------------

    def _forecast_cache_key(
        self,
        lat,
        lon,
        forecast_type,
        units,
        language,
    ):

        return (
            round(float(lat), 4),
            round(float(lon), 4),
            str(forecast_type),
            str(units),
            str(language),
        )

    #-------------------------------------------------------
    
    def travel_summary(
        self,
        weather: CurrentWeather,
    ) -> str:
    
        summary = []
    
        temp = weather.temperature
    
        if temp < 0:
            summary.append("Very cold conditions.")
        elif temp < 10:
            summary.append("Cold weather.")
        elif temp < 20:
            summary.append("Comfortable temperatures.")
        elif temp < 30:
            summary.append("Warm weather ideal for sightseeing.")
        else:
            summary.append("Very hot temperatures.")
    
        if weather.rain_1h > 0:
            summary.append(
                f"Rain detected ({weather.rain_1h:.1f} mm/hour)."
            )
    
        if weather.wind_speed > 12:
            summary.append(
                "Strong winds may affect outdoor activities."
            )
    
        if weather.uv_index >= 8:
            summary.append(
                "Very high UV levels. Sun protection recommended."
            )
    
        if weather.cloud_coverage < 30:
            summary.append(
                "Excellent visibility for sightseeing and photography."
            )
    
        if weather.cloud_coverage > 80:
            summary.append(
                "Cloudy conditions expected."
            )
    
        return " ".join(summary)
        
    #--------------------------------------------------------
    
    def destination_suitability(
        self,
        weather: CurrentWeather,
    ) -> dict:
    
        scores = {
            "beach": 50,
            "hiking": 50,
            "sightseeing": 50,
            "photography": 50,
            "nightlife": 50,
            "family": 50,
        }
    
        temp = weather.temperature
    
        rain = weather.rain_1h
    
        wind = weather.wind_speed
    
        clouds = weather.cloud_coverage
    
        # -----------------------------------
        # Beach
        # -----------------------------------
    
        if 24 <= temp <= 33:
            scores["beach"] += 35
    
        if rain > 0:
            scores["beach"] -= 40
    
        if wind > 12:
            scores["beach"] -= 15
    
        # -----------------------------------
        # Hiking
        # -----------------------------------
    
        if 12 <= temp <= 25:
            scores["hiking"] += 35
    
        if temp > 33:
            scores["hiking"] -= 30
    
        if rain > 0:
            scores["hiking"] -= 20
    
        # -----------------------------------
        # Sightseeing
        # -----------------------------------
    
        if 15 <= temp <= 28:
            scores["sightseeing"] += 30
    
        if rain > 0:
            scores["sightseeing"] -= 20
    
        # -----------------------------------
        # Photography
        # -----------------------------------
    
        if 20 <= clouds <= 60:
            scores["photography"] += 30
    
        if clouds < 10:
            scores["photography"] += 15
    
        if rain > 0:
            scores["photography"] -= 15
    
        # -----------------------------------
        # Nightlife
        # -----------------------------------
    
        if temp > 12:
            scores["nightlife"] += 25
    
        if rain > 5:
            scores["nightlife"] -= 10
    
        # -----------------------------------
        # Family
        # -----------------------------------
    
        if 18 <= temp <= 30:
            scores["family"] += 30
    
        if rain > 0:
            scores["family"] -= 20
    
        for key in scores:
            scores[key] = max(
                0,
                min(
                    100,
                    int(scores[key]),
                ),
            )
    
        return scores
        
    #--------------------------------------------------------
    
    def _validate_units(
            self,
            units: str,
        ) -> str:
    
            units = str(units).lower().strip()
    
            if units not in self.VALID_UNITS:
                return "metric"
    
            return units
            
    # ------------------------------------------------------
            
    async def _request(
        self,
        url: str,
        params: dict,
    ):

        retries = 3

        last_error = None

        for attempt in range(retries):

            try:

                async with self.session.get(
                    url,
                    params=params,
                ) as response:

                    logger.info(
                        "OpenWeather request: %s",
                        response.url,
                    )

                    # ----------------------------------
                    # HTTP ERRORS
                    # ----------------------------------

                    if response.status == 401:

                        raise RuntimeError(
                            "Invalid OpenWeather API key."
                        )

                    if response.status == 403:

                        raise RuntimeError(
                            "OpenWeather access denied."
                        )

                    if response.status == 404:

                        raise RuntimeError(
                            "Requested resource not found."
                        )

                    if response.status == 429:

                        raise RuntimeError(
                            "OpenWeather rate limit exceeded."
                        )

                    if response.status >= 500:

                        raise RuntimeError(
                            f"OpenWeather server error ({response.status})"
                        )

                    response.raise_for_status()

                    try:

                        data = await response.json()

                    except aiohttp.ContentTypeError:

                        text = await response.text()

                        raise RuntimeError(
                            f"Invalid JSON response:\n{text[:300]}"
                        )

                    return data

            except (
                aiohttp.ClientConnectionError,
                aiohttp.ClientConnectorError,
            ) as e:

                last_error = e

                logger.warning(
                    "Connection failed (%d/%d): %s",
                    attempt + 1,
                    retries,
                    e,
                )

            except asyncio.TimeoutError as e:

                last_error = e

                logger.warning(
                    "Timeout (%d/%d)",
                    attempt + 1,
                    retries,
                )

            except aiohttp.ClientResponseError as e:

                last_error = e

                logger.warning(
                    "HTTP %s (%d/%d)",
                    e.status,
                    attempt + 1,
                    retries,
                )

            except Exception as e:

                last_error = e

                logger.warning(
                    "Unexpected error (%d/%d): %s",
                    attempt + 1,
                    retries,
                    e,
                )

            if attempt < retries - 1:

                wait = attempt + 1

                logger.info(
                    "Retrying in %d second(s)...",
                    wait,
                )

                await asyncio.sleep(wait)

        raise RuntimeError(
            f"OpenWeather request failed after {retries} attempts.\n"
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------

    async def geocode(
        self,
        city: str,
        language: str = "en",
    ) -> dict:
    
        _check_api_key()
    
        city = str(city).strip()
    
        if not city:
            raise ValueError(
                "City name cannot be empty."
            )
    
        cache_key = (
            city.lower(),
            language.lower(),
        )
    
        if cache_key in self.geo_cache:
    
            cached_timestamp, cached_result = (
                self.geo_cache[cache_key]
            )
    
            age = (
                datetime.now().timestamp()
                - cached_timestamp
            )
    
            if age < self.geo_cache_ttl:
    
                logger.info(
                    "Using cached geocoding for '%s'",
                    city,
                )
    
                return cached_result
    
            del self.geo_cache[cache_key]
    
        logger.info(
            "Geocoding city '%s'",
            city,
        )
    
        url = f"{BASE_URL}/geo/1.0/direct"
    
        params = {
            "q": city,
            "limit": 1,
            "appid": OPENWEATHER_API_KEY,
        }
    
        data = await self._request(
            url,
            params,
        )
    
        if not data:
            raise ValueError(
                f"City '{city}' not found."
            )
    
        result = data[0]
    
        # -----------------------------
        # CACHE SAVE
        # -----------------------------
    
        self.geo_cache[cache_key] = (
            datetime.now().timestamp(),
            result,
        )
    
        logger.info(
            "Geocoding cached for '%s'",
            city,
        )
    
        return result

    # ------------------------------------------------------

    async def current_weather(
        self,
        city: str,
        language: str = "en",
        units: str = "metric",
    ) -> CurrentWeather:
    
        _check_api_key()
    
        units = self._validate_units(units)
    
        geo = await self.geocode(
            city,
            language=language,
        )
    
        weather = await self.current_weather_coordinates(
            lat=geo["lat"],
            lon=geo["lon"],
            language=language,
            units=units,
        )
    
        # fill geocoding information
        weather.city = geo.get(
            "name",
            city,
        )
    
        weather.country = geo.get(
            "country",
            "",
        )
    
        return weather


    # ------------------------------------------------------
    
    async def current_weather_coordinates(
        self,
        lat: float,
        lon: float,
        language: str = "en",
        units: str = "metric",
    ) -> CurrentWeather:
    
        units = self._validate_units(units)
    
        url = f"{BASE_URL}/data/2.5/weather"

        params = {
            "lat": lat,
            "lon": lon,
            "appid": OPENWEATHER_API_KEY,
            "units": units,
            "lang": language,
        }
        
        data = await self._request(url, params)
        
        current = data
    
        main = current.get("main", {})
        wind = current.get("wind", {})
        sys = current.get("sys", {})
        
        return CurrentWeather(
            city="",
            country="",
        
            temperature=main.get(
                "temp",
                0.0,
            ),
        
            feels_like=main.get(
                "feels_like",
                0.0,
            ),
        
            humidity=main.get(
                "humidity",
                0,
            ),
        
            pressure=main.get(
                "pressure",
                0,
            ),
        
            wind_speed=wind.get(
                "speed",
                0.0,
            ),
        
            description=current.get(
                "weather",
                [{}],
            )[0].get(
                "description",
                "",
            ),
        
            icon=current.get(
                "weather",
                [{}],
            )[0].get(
                "icon",
                "",
            ),
        
            visibility=current.get(
                "visibility",
                0,
            ),
        
            sunrise=datetime.fromtimestamp(
                sys.get(
                    "sunrise",
                    0,
                )
            ),
        
            sunset=datetime.fromtimestamp(
                sys.get(
                    "sunset",
                    0,
                )
            ),
        
            # Not available in free weather endpoint
            uv_index=0.0,
        
            cloud_coverage=current.get(
                "clouds",
                {},
            ).get(
                "all",
                0,
            ),
        
            rain_1h=current.get(
                "rain",
                {},
            ).get(
                "1h",
                0.0,
            ),
        
            snow_1h=current.get(
                "snow",
                {},
            ).get(
                "1h",
                0.0,
            ),
        )
        
    # ------------------------------------------------------
    
    async def hourly_forecast_coordinates(
        self,
        lat: float,
        lon: float,
        hours: int = 24,
        language: str = "en",
        units: str = "metric",
    ) -> list[HourlyForecast]:
    
        units = self._validate_units(units)
    
        url = f"{BASE_URL}/data/2.5/forecast"
    
        params = {
            "lat": lat,
            "lon": lon,
            "appid": OPENWEATHER_API_KEY,
            "units": units,
            "lang": language,
        }
    
        data = await self._request(
            url,
            params,
        )
    
        forecasts = []
    
        # OpenWeather 2.5 forecast uses 3-hour intervals
        max_entries = min(
            hours,
            len(data.get("list", [])),
        )
    
        for hour in data.get(
            "list",
            [],
        )[:max_entries]:
    
            main = hour.get(
                "main",
                {},
            )
    
            clouds = hour.get(
                "clouds",
                {},
            )
    
            weather = hour.get(
                "weather",
                [{}],
            )[0]
    
            forecasts.append(
                HourlyForecast(
                    timestamp=datetime.fromtimestamp(
                        hour.get(
                            "dt",
                            0,
                        )
                    ),
    
                    temperature=main.get(
                        "temp",
                        0.0,
                    ),
    
                    humidity=main.get(
                        "humidity",
                        0,
                    ),
    
                    rain_probability=hour.get(
                        "pop",
                        0.0,
                    ),
    
                    cloud_coverage=clouds.get(
                        "all",
                        0,
                    ),
    
                    rain_amount=hour.get(
                        "rain",
                        {},
                    ).get(
                        "3h",
                        0.0,
                    ),
    
                    icon=weather.get(
                        "icon",
                        "",
                    ),
    
                    description=weather.get(
                        "description",
                        "",
                    ),
                )
            )
    
        return forecasts
        
    async def daily_forecast_coordinates(
        self,
        lat: float,
        lon: float,
        days: int = 5,
        language: str = "en",
        units: str = "metric",
    ) -> list[DailyForecast]:
    
        units = self._validate_units(units)
    
        url = f"{BASE_URL}/data/2.5/forecast"
    
        params = {
            "lat": lat,
            "lon": lon,
            "appid": OPENWEATHER_API_KEY,
            "units": units,
            "lang": language,
        }
    
        data = await self._request(
            url,
            params,
        )
    
        forecasts = []
    
        # OpenWeather returns forecasts every 3 hours
        # 8 forecasts = 24 hours
        daily_entries = data.get(
            "list",
            [],
        )[::8]
    
        for day in daily_entries[:days]:
    
            main = day.get(
                "main",
                {},
            )
    
            weather = day.get(
                "weather",
                [{}],
            )[0]
    
            clouds = day.get(
                "clouds",
                {},
            )
    
            wind = day.get(
                "wind",
                {},
            )
    
            forecasts.append(
                DailyForecast(
                    date=datetime.fromtimestamp(
                        day["dt"]
                    ),
    
                    temp_min=main.get(
                        "temp_min",
                        main.get(
                            "temp",
                            0.0,
                        ),
                    ),
    
                    temp_max=main.get(
                        "temp_max",
                        main.get(
                            "temp",
                            0.0,
                        ),
                    ),
    
                    humidity=main.get(
                        "humidity",
                        0,
                    ),
    
                    wind_speed=wind.get(
                        "speed",
                        0.0,
                    ),
    
                    cloud_coverage=clouds.get(
                        "all",
                        0,
                    ),
    
                    description=weather.get(
                        "description",
                        "",
                    ),
    
                    icon=weather.get(
                        "icon",
                        "",
                    ),
    
                    rain_probability=day.get(
                        "pop",
                        0.0,
                    ),
                )
            )
    
        return forecasts
        
    async def destination_weather(
        self,
        destination,
        language: str = "en",
        units: str = "metric",
    ):
    
        lat = getattr(
            destination,
            "latitude",
            None,
        )
    
        lon = getattr(
            destination,
            "longitude",
            None,
        )
    
        if lat is None or lon is None:
            raise ValueError(
                "Destination coordinates missing."
            )
    
        return await self.current_weather_coordinates(
            lat=lat,
            lon=lon,
            language=language,
            units=units,
        )
        
    async def destination_daily_forecast(
        self,
        destination,
        days: int = 7,
        language: str = "en",
        units: str = "metric",
    ):
    
        lat = getattr(
            destination,
            "latitude",
            None,
        )
    
        lon = getattr(
            destination,
            "longitude",
            None,
        )
    
        if lat is None or lon is None:
            raise ValueError(
                "Destination coordinates missing."
            )
    
        return await self.daily_forecast_coordinates(
            lat=lat,
            lon=lon,
            days=days,
            language=language,
            units=units,
        )
        
    async def destination_hourly_forecast(
        self,
        destination,
        hours: int = 24,
        language: str = "en",
        units: str = "metric",
    ):
    
        lat = getattr(
            destination,
            "latitude",
            None,
        )
    
        lon = getattr(
            destination,
            "longitude",
            None,
        )
    
        if lat is None or lon is None:
            raise ValueError(
                "Destination coordinates missing."
            )
    
        return await self.hourly_forecast_coordinates(
            lat=lat,
            lon=lon,
            hours=hours,
            language=language,
            units=units,
        )

    async def hourly_forecast(
        self,
        city: str,
        hours: int = 24,
        language: str = "en",
        units: str = "metric",
    ) -> List[HourlyForecast]:
    
        _check_api_key()
    
        units = self._validate_units(
            units,
        )
    
        geo = await self.geocode(
            city,
            language=language,
        )
    
        forecasts = await self.hourly_forecast_coordinates(
            lat=geo["lat"],
            lon=geo["lon"],
            hours=hours,
            language=language,
            units=units,
        )
    
        return forecasts

    # ------------------------------------------------------

    async def daily_forecast(
        self,
        city: str,
        days: int = 5,
        language: str = "en",
        units: str = "metric",
    ) -> List[DailyForecast]:
    
        _check_api_key()
    
        units = self._validate_units(
            units,
        )
    
        geo = await self.geocode(
            city,
            language=language,
        )
    
        forecasts = await self.daily_forecast_coordinates(
            lat=geo["lat"],
            lon=geo["lon"],
            days=days,
            language=language,
            units=units,
        )
    
        return forecasts


    async def weather_alerts(
        self,
        city: str,
        language: str = "en",
    ) -> list[WeatherAlert]:
    
        _check_api_key()
    
        # OpenWeather weather alerts require the
        # paid One Call 3.0 subscription.
        # Free accounts do not have access.
    
        logger.warning(
            "Weather alerts are unavailable "
            "without an OpenWeather One Call "
            "subscription."
        )
    
        return []

# ==========================================================
# EXAMPLE
# ==========================================================

async def main():

    service = WeatherService()

    current = await service.current_weather("Athens")

    print(current)

    daily = await service.daily_forecast("Athens")

    print(daily[0])

    hourly = await service.hourly_forecast("Athens")

    print(alerts)


if __name__ == "__main__":

    asyncio.run(main())