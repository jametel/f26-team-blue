import inspect, django.contrib.auth.views as av
print("Django:", __import__("django").get_version())
src = inspect.getsource(av.LoginView.get_redirect_url)
print(src)
