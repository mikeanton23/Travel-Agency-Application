import requests
from app.db.database import SessionLocal
from app.db.models import Destination


def load_random_cities():
    url = "http://geodb-free-service.wirefreethought.com/v1/geo/cities?limit=10"

    response = requests.get(url)
    data = response.json()

    db = SessionLocal()

    for city in data["data"]:
        dest = Destination(
            name=city["city"],
            country=city["country"],
            latitude=city["latitude"],
            longitude=city["longitude"],
            description=f"Explore {city['city']} in {city['country']}",
            avg_cost_per_day=50 + (hash(city["city"]) % 100)
        )

        db.add(dest)

    db.commit()
    db.close()

    print("? Random cities loaded")