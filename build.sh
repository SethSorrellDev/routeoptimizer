#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
flask db upgrade
python seed_roles.py
python seed_plant.py
