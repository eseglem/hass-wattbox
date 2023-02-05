init:
	virtualenv venv -p python3
	pip install homeassistant
	ln -sf "${PWD}/custom_components" "${PWD}/config/custom_components"
	echo "${PWD}/../pywattbox" venv/lib/python3.10/site-packages/pywattbot.pth
