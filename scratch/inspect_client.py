from thetadata import ThetaClient
import inspect

client_methods = inspect.getmembers(ThetaClient, predicate=inspect.isfunction)
print("ThetaClient methods:")
for name, member in client_methods:
    if not name.startswith("_"):
        print(f"  {name}")
