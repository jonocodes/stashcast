web: python manage.py runserver
worker: watchmedo auto-restart --directory=./media --directory=./stashcast --pattern="*.py" --recursive -- python manage.py run_huey
testserver: python test_server.py
