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
# PHASE 2  API CACHE (persistent tier of cache_service)
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
# PHASE 1  NORMALIZED SCHEMA
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
    # Agency role: agent | manager | admin. is_admin is kept so older
    # checks keep working; manager and admin both see the whole office.
    role = Column(String(20), nullable=False, default="agent")
    agency_id = Column(Integer,
                       ForeignKey("agencies.id", ondelete="SET NULL"))
    phone = Column(String(60))
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
# PHASE 3  RAG KNOWLEDGE BASE
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
# PHASE 5  MONITORING & NOTIFICATIONS
# ==========================================================


class ApiUsageLog(Base):
    """One row per outbound API call  the admin dashboard's raw data.

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
# AGENCY: offices, agents, clients, quotes, cash
# ==========================================================
# Each agent keeps their own client book; managers and admins see the
# whole office. Receipts from every agent land in one office cash
# account so the balance is tracked centrally.


class Agency(Base):
    __tablename__ = "agencies"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    legal_name = Column(String(200))
    vat_number = Column(String(40))
    address = Column(Text)
    phone = Column(String(60))
    email = Column(String(255))
    # Greek VAT on service charges for domestic services.
    default_vat_rate = Column(Float, nullable=False, default=24.0)
    home_country_code = Column(String(2), nullable=False, default="GR")
    currency = Column(String(3), nullable=False, default="EUR")
    invoice_prefix = Column(String(10), nullable=False, default="INV")
    voucher_prefix = Column(String(10), nullable=False, default="VCH")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Client(Base):
    """A traveller or company on an agent's book."""

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    agency_id = Column(Integer,
                       ForeignKey("agencies.id", ondelete="CASCADE"),
                       nullable=False)
    # The agent who owns this relationship. Other agents cannot see it
    # unless they are a manager or admin.
    owner_agent_id = Column(Integer,
                            ForeignKey("users.id", ondelete="SET NULL"))
    full_name = Column(String(200), nullable=False)
    company_name = Column(String(200))
    email = Column(String(255))
    phone = Column(String(60))
    vat_number = Column(String(40))
    tax_office = Column(String(120))
    address = Column(Text)
    passport_number = Column(String(60))
    passport_expiry = Column(String(10))
    date_of_birth = Column(String(10))
    nationality = Column(String(80))
    notes = Column(Text)
    consent_marketing = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_clients_agency_owner", "agency_id", "owner_agent_id"),
        Index("ix_clients_name", "full_name"),
    )


class ClientNote(Base):
    __tablename__ = "client_notes"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer,
                       ForeignKey("clients.id", ondelete="CASCADE"),
                       nullable=False)
    author_id = Column(Integer,
                       ForeignKey("users.id", ondelete="SET NULL"))
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_client_notes_client", "client_id"),)


class Quote(Base):
    """A multi-service itinerary priced for one client."""

    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True)
    agency_id = Column(Integer,
                       ForeignKey("agencies.id", ondelete="CASCADE"),
                       nullable=False)
    client_id = Column(Integer,
                       ForeignKey("clients.id", ondelete="SET NULL"))
    agent_id = Column(Integer,
                      ForeignKey("users.id", ondelete="SET NULL"))
    reference = Column(String(30), nullable=False, unique=True)
    title = Column(String(250))
    status = Column(String(30), nullable=False, default="draft")
    currency = Column(String(3), nullable=False, default="EUR")
    travel_start = Column(String(10))
    travel_end = Column(String(10))
    pax_adults = Column(Integer, nullable=False, default=1)
    pax_children = Column(Integer, nullable=False, default=0)
    notes = Column(Text)
    terms = Column(Text)
    valid_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    items = relationship("QuoteItem", back_populates="quote",
                         cascade="all, delete-orphan",
                         order_by="QuoteItem.position")

    __table_args__ = (
        Index("ix_quotes_agency_status", "agency_id", "status"),
        Index("ix_quotes_agent", "agent_id"),
    )


class QuoteItem(Base):
    """One service line: hotel, ticket, transfer, car hire or tour.

    ``net_cost`` is what the supplier charges. ``service_charge`` is
    what the agency adds and is entered by the agent, never computed
    by the system. ``is_domestic`` drives whether VAT applies.
    """

    __tablename__ = "quote_items"

    id = Column(Integer, primary_key=True)
    quote_id = Column(Integer, ForeignKey("quotes.id",
                                          ondelete="CASCADE"),
                      nullable=False)
    position = Column(Integer, nullable=False, default=0)
    service_type = Column(String(20), nullable=False)
    title = Column(String(250), nullable=False)
    description = Column(Text)
    supplier = Column(String(120))
    supplier_reference = Column(String(120))
    starts_on = Column(String(10))
    ends_on = Column(String(10))
    quantity = Column(Integer, nullable=False, default=1)
    pax = Column(Integer)
    net_cost = Column(Float, nullable=False, default=0.0)
    service_charge = Column(Float, nullable=False, default=0.0)
    vat_rate = Column(Float, nullable=False, default=0.0)
    is_domestic = Column(Boolean, nullable=False, default=False)
    currency = Column(String(3), nullable=False, default="EUR")
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    quote = relationship("Quote", back_populates="items")

    __table_args__ = (
        Index("ix_quote_items_quote", "quote_id"),
    )


class CashAccount(Base):
    """One office account per agency; every receipt lands here."""

    __tablename__ = "cash_accounts"

    id = Column(Integer, primary_key=True)
    agency_id = Column(Integer,
                       ForeignKey("agencies.id", ondelete="CASCADE"),
                       nullable=False)
    name = Column(String(120), nullable=False, default="Office account")
    currency = Column(String(3), nullable=False, default="EUR")
    opening_balance = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("agency_id", "name", name="uq_cash_account"),
    )


class CashMovement(Base):
    """An immutable ledger line. Corrections are new reversing rows,
    never edits, so the office balance can always be reconstructed."""

    __tablename__ = "cash_movements"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer,
                        ForeignKey("cash_accounts.id",
                                   ondelete="CASCADE"),
                        nullable=False)
    agent_id = Column(Integer,
                      ForeignKey("users.id", ondelete="SET NULL"))
    client_id = Column(Integer,
                       ForeignKey("clients.id", ondelete="SET NULL"))
    quote_id = Column(Integer,
                      ForeignKey("quotes.id", ondelete="SET NULL"))
    direction = Column(String(3), nullable=False)      # in | out
    method = Column(String(20), nullable=False)        # cash|card|iris
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="EUR")
    reference = Column(String(120))
    description = Column(Text)
    reverses_id = Column(Integer,
                         ForeignKey("cash_movements.id",
                                    ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_cash_movements_account_created",
              "account_id", "created_at"),
        Index("ix_cash_movements_agent", "agent_id"),
    )
