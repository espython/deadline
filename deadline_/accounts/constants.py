NOTIFICATION_TOKEN_EXPIRY_MINUTES = 1440
NOTIFICATION_SECRET_KEY = 't0ps3cr3t123'  # TODO: Load from env
FACEBOOK_PROFILE_REGEX = r'^(?:http(s)?:\/\/)?(?:www\.)?facebook\.com\/(?:(?:\w)*#!\/)?(?P<page_name>[\w\-]+)(((?=\/).+\/(?!\/))|(?!\/)|(\/?\?.+))$'
TWITTER_PROFILE_REGEX = r'^(?:http(s)?:\/\/)?(?:www\.)?twitter\.com\/(?:(?:\w)*#!\/)?(?P<profile_name>[\w\-]+)(\?[^\/]+)?$'
GITHUB_PROFILE_REGEX = r'^(?:http(s)?:\/\/)?(?:www\.)?github\.com\/(?:(?:\w)*#!\/)?(?P<profile_name>[\w\-]+)(\?[^\/]+)?$'
LINKEDIN_PROFILE_REGEX = r'^(?:http(s)?:\/\/)?(?:www\.)?linkedin\.com\/in/(?P<profile_name>[\w\-]+)(\?[^\/]+)?/?$'
