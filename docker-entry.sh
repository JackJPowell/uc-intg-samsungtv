#!/bin/bash

cd /usr/src/app
pip install --no-cache-dir -q -r requirements.txt
python intg-samsungtv/driver.py