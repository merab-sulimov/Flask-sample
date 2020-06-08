import baseconfig





class DevelopmentConfig(baseconfig.DevelopmentConfig):

    CUSTOM_TEMPLATE_FOLDER = 'templates'

    FRONTEND_BUILD_LOCATION = 'app/static/assets'



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