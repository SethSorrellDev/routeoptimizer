"""Entry point. `flask --app run.py run` or `python run.py`."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
