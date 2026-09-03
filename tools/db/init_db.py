"""Run once to create all tables."""
from tools.db.session import engine
from tools.db.models import Base

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("All tables created.")
