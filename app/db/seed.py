from app.db.database import engine, SessionLocal
from app.db.models import Base, Destination


def seed():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # Clear existing data (optional)
    db.query(Destination).delete()

    destinations = [
        Destination(
            name="Santorini",
            country="Greece",
            latitude=36.3932,
            longitude=25.4615,
            avg_cost_per_day=120,
            best_months=["May", "Jun", "Sep"],
            tags=["beach", "romantic", "luxury"],
            description="Famous for sunsets and white-blue houses.",
            image_urls=["https://images.unsplash.com/photo-1507525428034-b723cf961d3e"]
        ),
        Destination(
            name="Bali",
            country="Indonesia",
            latitude=-8.3405,
            longitude=115.0920,
            avg_cost_per_day=60,
            best_months=["May", "Jun", "Jul"],
            tags=["nature", "budget", "adventure"],
            description="Tropical paradise with temples and beaches.",
            image_urls=["https://images.unsplash.com/photo-1506744038136-46273834b3fb"]
        ),
        Destination(
            name="Paris",
            country="France",
            latitude=48.8566,
            longitude=2.3522,
            avg_cost_per_day=150,
            best_months=["Apr", "May", "Jun"],
            tags=["city", "romantic", "culture"],
            description="The city of lights and love.",
            image_urls=["https://images.unsplash.com/photo-1499856871958-5b9627545d1a"]
        )
    ]

    db.add_all(destinations)
    db.commit()
    db.close()

    print("? Database seeded!")


if __name__ == "__main__":
    seed()