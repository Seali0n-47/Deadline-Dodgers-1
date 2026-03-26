import csv
from sqlalchemy import create_engine, Column, Integer, Float, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ── Database setup ──────────────────────────────────────────────────────────
def push_to_db(csv_file_path="combined_expenses.csv"):
    # Replace these values with your PostgreSQL credentials
    DB_USER = "postgres"
    DB_PASSWORD = "1234"
    DB_HOST = "localhost"
    DB_PORT = "5432"
    DB_NAME = "ExpenseRecord"
    
    DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    try:
        engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
        Base = declarative_base()
        
        # ── Define the table ─────────────────────────────────────────────────────────
        class Expense(Base):
            __tablename__ = "expenses"
        
            id = Column(Integer, primary_key=True, autoincrement=True)
            expense_name = Column(String(100), nullable=False)
            expense_amount = Column(Float, nullable=False)
            sevLev = Column(Float, nullable=False)
        
        # Create the table if it does not exist
        Base.metadata.create_all(engine)
        
        # ── Prepare a session ───────────────────────────────────────────────────────
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # ── Read CSV and insert data ────────────────────────────────────────────────
        with open(csv_file_path, newline="") as csvfile:
            reader = csv.reader(csvfile)
            next(reader)  # Skip the header row
        
            for row in reader:
                expense_name, expense_amount, sevLev = row
                # Convert numeric values properly
                expense_amount = float(expense_amount)
                sevLev = float(sevLev)
        
                expense = Expense(
                    expense_name=expense_name.strip(),
                    expense_amount=expense_amount,
                    sevLev=sevLev
                )
                session.add(expense)
        
        # Commit the session to save all entries
        session.commit()
        session.close()
        
        print(f"Data from '{csv_file_path}' inserted successfully into the database!")
        return True
    except Exception as e:
        print(f"Failed to push to DB (database might be offline): {e}")
        return False

if __name__ == "__main__":
    push_to_db()