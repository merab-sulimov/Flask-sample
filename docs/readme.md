# Setting up development environment

First of all you'll need `VirtualBox` and `vagrant`.
Create a directory e.g. `/Users/developer/Dev/jobdone` and clone both `selfmarket` and `jobdone-frontend-build` into it.

`jobdone-frontend-build` contains pre-built frontend so all you have to do with it is to `git pull` from time to time to get in sync with frontend developers.

Now, go into `selfmarket` and run `vagrant up` to create a VM and preinstall requirements.
Once ready, log into VM using `./vagrant` script.

## Configuration

Create `config.py` file:
```
import baseconfig


class DevelopmentConfig(baseconfig.DevelopmentConfig):
    CUSTOM_TEMPLATE_FOLDER = '/vagrant_frontend_build/templates'
    FRONTEND_BUILD_LOCATION = '/vagrant_frontend_build/assets'

    USE_JOBDONE_IMAGE_SERVICE = True

    AWS_ACCESS_KEY = 'TODO'
    AWS_SECRET_KEY = 'TODO'
    AWS_SESSION_TOKEN = ''

    AWS_IMAGES_CONFIGURATION = {
        'bucket': 'selfmarkett_dev',
        'prefix': 'images_dev_TODO'
    }

    AWS_PROFILE_IMAGES_CONFIGURATION = {
        'bucket': 'selfmarkett_dev',
        'prefix': 'profile_images_dev_TODO'
    }
```

Override `TODO` with your own data (should be provided). 

## Test data

Now you can run a few commands to populate database with some fake data:
```
./manage.py add_test_categories
./manage.py add_test_users
./manage.py add_fake_products
```

## Run server

Run the following command in order to start the server:
`./manage.py runserver -h 0.0.0.0`

Open http://localhost:5000 in your browser.
