release: python manage.py makemigrations && python manage.py migrate --noinput
web: gunicorn config.wsgi --log-file -
