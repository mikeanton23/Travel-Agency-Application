# -*- coding: utf-8 -*-

from sqlalchemy import (
    Boolean, Column, Integer, String, Float, Text,
    ForeignKey, DateTime, JSON, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func


Base = declarative_base()


class Destination(Base):
    __tablename__ = "destinations"

    id = Column(Integer, primary_key=True)

    name = Column(String(150), nullable=False)
    country = Column(String(100), nullable=False)
    continent = Column(String(50))

    latitude = Column(Float)
    longitude = Column(Float)

    # Phase 1: optional links into the normalized geo hierarchy.
    country_id = Column(
        Integer, ForeignKey("countries.id", ondelete="SET NULL"),
        nullable=True,
    )
    city_id = Column(
        Integer, ForeignKey("cities.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Phase 1: columns seed.py referenced but the model lacked.
    tags = Column(JSON, nullable=True)
    best_months = Column(JSON, nullable=True)
    image_urls = Column(JSON, nullable=True)

    description = Column(Text)
    avg_cost_per_day = Column(Float)

    ai_score = Column(Float, default=0)
    score_summary = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    seasons = relationship(
        "Season",
        back_populates="destination",
        cascade="all, delete-orphan",
    )

    images = relationship(
        "Image",
        back_populates="destination",
        cascade="all, delete-orphan",
    )

    travel_plans = relationship(
        "TravelPlan",
        back_populates="destination",
        cascade="all, delete-orphan",
    )


class Season(Base):
    __tablename__ = "seasons"

    id = Column(Integer, primary_key=True)

    destination_id = Column(
        Integer,
        ForeignKey("destinations.id", ondelete="CASCADE"),
        nullable=False,
    )

    month = Column(String(10), nullable=False)

    destination = relationship("Destination", back_populates="seasons")


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True)

    destination_id = Column(
        Integer,
        ForeignKey("destinations.id", ondelete="CASCADE"),
        nullable=False,
    )

    url = Column(Text, nullable=False)

    destination = relationship("Destination", back_populates="images")


class TravelPlan(Base):
    __tablename__ = "travel_plans"

    id = Column(Integer, primary_key=True)

    destination_id = Column(
        Integer,
        ForeignKey("destinations.id", ondelete="CASCADE"),
        nullable=False,
    )

    month = Column(String(10), nullable=False)
    travelers = Column(String(50))
    continent = Column(String(50))

    days = Column(Integer, nullable=False)
    budget = Column(Float)

    user_preferences = Column(Text)
    plan_markdown = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    destination = relationship(
        "Destination",
        back_populates="travel_plans",
    )

# ==========================================================
# PHASE 2 – API CACHE (persistent tier of cache_service)
# ==========================================================



class ApiCache(Base):
    """Persistent cache of external API responses.

    ``cache_key`` is built by ``app.services.cache_service.make_cache_key``
    (namespace + SHA-256 of the call arguments). ``payload`` stores the
    JSON-encoded response; ``expires_at`` is checked on every read and
    expired rows are deleted lazily.
    """

    __tablename__ = "api_cache"

    cache_key = Column(String(120), primary_key=True)
    payload = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_api_cache_expires_at", "expires_at"),
    )


# ==========================================================
# PHASE 1 – NORMALIZED SCHEMA
# ==========================================================
# Geo hierarchy, users, trips, favorites, reviews, events,
# encrypted API keys, AI conversations, weather cache.
# All tables are additive: nothing existing was removed.


class Country(Base):
    __tablename__ = "countries"

    id = Column(Integer, primary_key=True)
    iso2 = Column(String(2), nullable=False, unique=True)
    iso3 = Column(String(3), unique=True)
    name = Column(String(120), nullable=False)
    continent = Column(String(50))
    currency_code = Column(String(3))
    languages = Column(JSON)
    flag_emoji = Column(String(8))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    regions = relationship("Region", back_populates="country",
                           cascade="all, delete-orphan")
    cities = relationship("City", back_populates="country",
                          cascade="all, delete-orphan")

    __table_args__ = (Index("ix_countries_name", "name"),)


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True)
    country_id = Column(Integer,
                        ForeignKey("countries.id", ondelete="CASCADE"),
                        nullable=False)
    name = Column(String(120), nullable=False)

    country = relationship("Country", back_populates="regions")
    cities = relationship("City", back_populates="region")

    __table_args__ = (
        UniqueConstraint("country_id", "name", name="uq_region_per_country"),
    )


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True)
    country_id = Column(Integer,
                        ForeignKey("countries.id", ondelete="CASCADE"),
                        nullable=False)
    region_id = Column(Integer,
                       ForeignKey("regions.id", ondelete="SET NULL"))
    name = Column(String(120), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    population = Column(Integer)
    timezone = Column(String(64))
    iata_city_code = Column(String(3))   # resolved via Amadeus

    country = relationship("Country", back_populates="cities")
    region = relationship("Region", back_populates="cities")
    hotels = relationship("Hotel", back_populates="city")

    __table_args__ = (
        Index("ix_cities_name", "name"),
        Index("ix_cities_country_id", "country_id"),
        Index("ix_cities_lat_lon", "latitude", "longitude"),
    )


class Hotel(Base):
    __tablename__ = "hotels"

    id = Column(Integer, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id", ondelete="CASCADE"))
    external_id = Column(String(64))        # e.g. Amadeus hotelId
    source = Column(String(30), nullable=False, default="amadeus")
    name = Column(String(200), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    rating = Column(Float)
    last_price_total = Column(Float)        # last real quote seen
    last_price_currency = Column(String(3))
    last_price_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    city = relationship("City", back_populates="hotels")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_hotel_source_ext"),
        Index("ix_hotels_city_id", "city_id"),
    )


class Attraction(Base):
    __tablename__ = "attractions"

    id = Column(Integer, primary_key=True)
    destination_id = Column(Integer,
                            ForeignKey("destinations.id", ondelete="CASCADE"),
                            nullable=False)
    external_id = Column(String(120))       # e.g. Geoapify place_id
    source = Column(String(30), nullable=False, default="geoapify")
    name = Column(String(200), nullable=False)
    category = Column(String(120))
    latitude = Column(Float)
    longitude = Column(Float)
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "external_id",
                         name="uq_attraction_source_ext"),
        Index("ix_attractions_destination_id", "destination_id"),
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    destination_id = Column(Integer,
                            ForeignKey("destinations.id",
                                       ondelete="CASCADE"))
    external_id = Column(String(120))
    source = Column(String(30), nullable=False, default="ticketmaster")
    name = Column(String(250), nullable=False)
    category = Column(String(120))
    starts_at = Column(DateTime(timezone=True))
    venue = Column(String(250))
    url = Column(Text)
    price_min = Column(Float)
    price_max = Column(Float)
    currency = Column(String(3))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_event_source_ext"),
        Index("ix_events_destination_starts",
              "destination_id", "starts_at"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(120))
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True))

    preferences = relationship("UserPreference", back_populates="user",
                               uselist=False, cascade="all, delete-orphan")
    trips = relationship("Trip", back_populates="user",
                         cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="user",
                             cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, unique=True)
    home_currency = Column(String(3), default="EUR")
    home_airport = Column(String(3))
    daily_budget = Column(Float)
    travel_style = Column(JSON)     # e.g. ["romantic", "food", "nature"]
    dietary = Column(JSON)
    accessibility = Column(JSON)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="preferences")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)
    destination_id = Column(Integer,
                            ForeignKey("destinations.id",
                                       ondelete="SET NULL"))
    title = Column(String(200), nullable=False)
    starts_on = Column(DateTime(timezone=True))
    ends_on = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="draft")
    budget_total = Column(Float)
    currency = Column(String(3), default="EUR")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="trips")
    items = relationship("TripItem", back_populates="trip",
                         cascade="all, delete-orphan",
                         order_by="TripItem.position")

    __table_args__ = (Index("ix_trips_user_id", "user_id"),)


class TripItem(Base):
    __tablename__ = "trip_items"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"),
                     nullable=False)
    position = Column(Integer, nullable=False, default=0)
    kind = Column(String(30), nullable=False)  # flight/hotel/activity/note
    title = Column(String(250), nullable=False)
    scheduled_at = Column(DateTime(timezone=True))
    reference = Column(JSON)      # raw offer payload (real API data)
    price_total = Column(Float)
    currency = Column(String(3))

    trip = relationship("Trip", back_populates="items")

    __table_args__ = (Index("ix_trip_items_trip_id", "trip_id"),)


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)
    destination_id = Column(Integer,
                            ForeignKey("destinations.id",
                                       ondelete="CASCADE"),
                            nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="favorites")

    __table_args__ = (
        UniqueConstraint("user_id", "destination_id", name="uq_favorite"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    destination_id = Column(Integer,
                            ForeignKey("destinations.id",
                                       ondelete="CASCADE"),
                            nullable=False)
    rating = Column(Integer, nullable=False)  # 1..5, enforce in service
    title = Column(String(200))
    body = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_reviews_destination_id", "destination_id"),
    )


class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    query = Column(Text, nullable=False)
    parsed_filters = Column(JSON)
    results_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_search_history_user_created", "user_id", "created_at"),
    )


class WeatherCache(Base):
    """Structured weather snapshots (complements the generic api_cache)."""

    __tablename__ = "weather_cache"

    id = Column(Integer, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    kind = Column(String(20), nullable=False)  # current / forecast
    payload = Column(JSON, nullable=False)
    source = Column(String(30), nullable=False, default="open-meteo")
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_weather_cache_lookup",
              "latitude", "longitude", "kind", "expires_at"),
    )


class ApiKey(Base):
    """Encrypted per-provider API keys managed from the Settings page.

    ``encrypted_value`` is Fernet ciphertext (see app.utils.crypto);
    plaintext keys are never stored.
    """

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    provider = Column(String(60), nullable=False, unique=True)
    encrypted_value = Column(Text, nullable=False)
    is_valid = Column(Boolean)               # None = never validated
    last_validated_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String(250))
    provider = Column(String(30))    # openai / anthropic / ollama / ...
    model = Column(String(80))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    messages = relationship("AiMessage", back_populates="conversation",
                            cascade="all, delete-orphan",
                            order_by="AiMessage.id")


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer,
                             ForeignKey("ai_conversations.id",
                                        ondelete="CASCADE"),
                             nullable=False)
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    tokens = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("AiConversation", back_populates="messages")

    __table_args__ = (
        Index("ix_ai_messages_conversation_id", "conversation_id"),
    )


# ==========================================================
# PHASE 3 – RAG KNOWLEDGE BASE
# ==========================================================


class KbDocument(Base):
    """A fetched knowledge source (Wikipedia / Wikivoyage page)."""

    __tablename__ = "kb_documents"

    id = Column(Integer, primary_key=True)
    destination_id = Column(Integer,
                            ForeignKey("destinations.id",
                                       ondelete="CASCADE"))
    source = Column(String(30), nullable=False)   # wikipedia / wikivoyage
    title = Column(String(300), nullable=False)
    url = Column(Text)
    language = Column(String(8), nullable=False, default="en")
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    chunks = relationship("KbChunk", back_populates="document",
                          cascade="all, delete-orphan",
                          order_by="KbChunk.chunk_index")

    __table_args__ = (
        UniqueConstraint("source", "title", "language",
                         name="uq_kb_doc_source_title_lang"),
    )


class KbChunk(Base):
    """A chunk of source text plus its embedding vector (JSON array).

    The JSON column keeps the store portable; swapping in pgvector or
    FAISS later only changes the similarity search implementation in
    ``app/services/rag/store.py``.
    """

    __tablename__ = "kb_chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer,
                         ForeignKey("kb_documents.id", ondelete="CASCADE"),
                         nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(JSON)                 # list[float] or NULL
    embedding_model = Column(String(80))

    document = relationship("KbDocument", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index",
                         name="uq_kb_chunk_position"),
        Index("ix_kb_chunks_document_id", "document_id"),
    )


# ==========================================================
# PHASE 5 – MONITORING & NOTIFICATIONS
# ==========================================================


class ApiUsageLog(Base):
    """One row per outbound API call — the admin dashboard's raw data.

    Written best-effort by the metrics recorder hooked into
    ``HttpJsonClient``; requests never fail because logging failed.
    """

    __tablename__ = "api_usage"

    id = Column(Integer, primary_key=True)
    provider = Column(String(60), nullable=False)
    method = Column(String(8), nullable=False)
    host = Column(String(200), nullable=False)
    status_code = Column(Integer)
    ok = Column(Boolean, nullable=False, default=True)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_api_usage_provider_created", "provider", "created_at"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)
    kind = Column(String(30), nullable=False, default="info")
    title = Column(String(250), nullable=False)
    body = Column(Text)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )


# ==========================================================
# HOTEL ACQUISITION — inventory, offers, leads, payments
# ==========================================================
# Additive: the existing Hotel model (Phase 1) is unchanged and is
# referenced by these tables.


class HotelProvider(Base):
    """A configured hotel supplier (amadeus, hotelbeds, expedia…)."""

    __tablename__ = "hotel_providers"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), nullable=False, unique=True)
    label = Column(String(120), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    priority = Column(Integer, nullable=False, default=100)
    last_success_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    last_error_at = Column(DateTime(timezone=True))
    rate_limit_note = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HotelRoom(Base):
    __tablename__ = "hotel_rooms"

    id = Column(Integer, primary_key=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"),
                      nullable=False)
    external_id = Column(String(120))
    name = Column(String(200), nullable=False)
    max_occupancy = Column(Integer)
    bed_type = Column(String(80))
    size_sqm = Column(Float)
    amenities = Column(JSON)

    __table_args__ = (
        Index("ix_hotel_rooms_hotel_id", "hotel_id"),
    )


class HotelOffer(Base):
    """A normalized, real supplier quote. Never written unless it came
    from a live provider response; ``expires_at`` governs staleness."""

    __tablename__ = "hotel_offers"

    id = Column(Integer, primary_key=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"),
                      nullable=False)
    supplier = Column(String(40), nullable=False)
    room_id = Column(String(120))
    room_name = Column(String(200))
    board_type = Column(String(40))        # room_only/breakfast/half…
    occupancy = Column(Integer, nullable=False, default=2)
    check_in = Column(String(10), nullable=False)   # ISO date
    check_out = Column(String(10), nullable=False)
    nights = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    base_price = Column(Float)
    taxes = Column(Float)
    fees = Column(Float)
    total_price = Column(Float, nullable=False)
    cancellation_policy = Column(String(200))
    refundable = Column(Boolean)
    availability = Column(Boolean, nullable=False, default=True)
    deep_link = Column(Text)
    retrieved_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_hotel_offers_lookup",
              "hotel_id", "check_in", "check_out", "occupancy"),
        Index("ix_hotel_offers_expires", "expires_at"),
    )


class HotelOfferRequest(Base):
    """A customer lead: 'can you beat this price?'"""

    __tablename__ = "hotel_offer_requests"

    id = Column(Integer, primary_key=True)
    customer_name = Column(String(160), nullable=False)
    customer_email = Column(String(255), nullable=False)
    customer_phone = Column(String(60))
    destination = Column(String(160))
    hotel_id = Column(Integer, ForeignKey("hotels.id", ondelete="SET NULL"))
    hotel_name = Column(String(200))
    check_in = Column(String(10))
    check_out = Column(String(10))
    guests = Column(Integer, default=2)
    rooms = Column(Integer, default=1)
    room_type = Column(String(200))
    meal_plan = Column(String(40))
    current_provider = Column(String(80))
    competitor_price = Column(Float)
    currency = Column(String(3))
    competitor_url = Column(Text)
    customer_message = Column(Text)
    consent = Column(Boolean, nullable=False, default=False)
    status = Column(String(30), nullable=False, default="new")
    assigned_to = Column(Integer,
                         ForeignKey("users.id", ondelete="SET NULL"))
    internal_notes = Column(Text)
    offer_deadline = Column(DateTime(timezone=True))
    source_page = Column(String(250))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_hotel_offer_requests_status_created",
              "status", "created_at"),
    )


class CompetitorComparison(Base):
    """Evidence backing any 'cheaper than X' claim. No row, no claim."""

    __tablename__ = "competitor_comparisons"

    id = Column(Integer, primary_key=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"))
    our_offer_id = Column(Integer,
                          ForeignKey("customer_offers.id",
                                     ondelete="CASCADE"))
    competitor = Column(String(80), nullable=False)
    competitor_price = Column(Float, nullable=False)
    competitor_currency = Column(String(3), nullable=False)
    competitor_room = Column(String(200))
    competitor_board = Column(String(40))
    competitor_cancellation = Column(String(200))
    competitor_taxes = Column(Float)
    competitor_total = Column(Float, nullable=False)
    comparison_timestamp = Column(DateTime(timezone=True),
                                  nullable=False)
    source_type = Column(String(40), nullable=False)  # supplier_api/
    # customer_reported/manual_staff_check
    verification_status = Column(String(30), nullable=False,
                                 default="unverified")


class CustomerOffer(Base):
    """A staff-prepared offer delivered by secure token link."""

    __tablename__ = "customer_offers"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer,
                        ForeignKey("hotel_offer_requests.id",
                                   ondelete="CASCADE"),
                        nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    hotel_name = Column(String(200), nullable=False)
    room_description = Column(String(250))
    board_type = Column(String(40))
    check_in = Column(String(10))
    check_out = Column(String(10))
    guests = Column(Integer)
    rooms = Column(Integer)
    conditions = Column(Text)
    cancellation_policy = Column(String(250))
    reference_price = Column(Float)      # only if verified comparable
    our_price = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)
    status = Column(String(30), nullable=False, default="prepared")
    created_by = Column(Integer, ForeignKey("users.id",
                                            ondelete="SET NULL"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True))
    opened_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_customer_offers_request", "request_id"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    offer_id = Column(Integer,
                      ForeignKey("customer_offers.id",
                                 ondelete="CASCADE"),
                      nullable=False)
    provider = Column(String(40), nullable=False, default="stripe")
    provider_payment_id = Column(String(200))
    provider_session_id = Column(String(200))
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    failure_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_payments_offer", "offer_id"),
        Index("ix_payments_provider_id", "provider_payment_id"),
    )


class EmailLog(Base):
    __tablename__ = "email_log"

    id = Column(Integer, primary_key=True)
    to_email = Column(String(255), nullable=False)
    subject = Column(String(300), nullable=False)
    kind = Column(String(50), nullable=False)
    request_id = Column(Integer,
                        ForeignKey("hotel_offer_requests.id",
                                   ondelete="SET NULL"))
    offer_id = Column(Integer,
                      ForeignKey("customer_offers.id",
                                 ondelete="SET NULL"))
    provider = Column(String(40))
    success = Column(Boolean, nullable=False, default=False)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_email_log_created", "created_at"),
    )


class SearchEvent(Base):
    """Privacy-conscious funnel analytics: no PII, no raw IPs."""

    __tablename__ = "search_events"

    id = Column(Integer, primary_key=True)
    event = Column(String(50), nullable=False)
    destination = Column(String(160))
    hotel_id = Column(Integer)
    session_hash = Column(String(64))     # salted hash, not an identity
    attributes = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_search_events_event_created", "event", "created_at"),
    )


class OfferEvent(Base):
    __tablename__ = "offer_events"

    id = Column(Integer, primary_key=True)
    offer_id = Column(Integer,
                      ForeignKey("customer_offers.id",
                                 ondelete="CASCADE"))
    request_id = Column(Integer,
                        ForeignKey("hotel_offer_requests.id",
                                   ondelete="CASCADE"))
    event = Column(String(50), nullable=False)
    detail = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_offer_events_offer", "offer_id"),
    )
