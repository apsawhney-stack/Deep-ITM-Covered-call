import os
import sys
import urllib.request
import tarfile
import shutil

def download_and_extract_java():
    jdk_dir = os.path.abspath("data/jdk")
    java_bin_dir = os.path.join(jdk_dir, "jdk-17.0.8.1+7/Contents/Home/bin") # Or search for Contents/Home/bin dynamically
    
    if os.path.exists(jdk_dir):
        print("JDK directory already exists.")
        # Let's search for the java binary
        java_bin = find_java_binary(jdk_dir)
        if java_bin:
            print(f"Found existing Java at: {java_bin}")
            return java_bin
        else:
            print("Java binary not found in existing JDK directory. Re-downloading...")
            shutil.rmtree(jdk_dir)
            
    os.makedirs(jdk_dir, exist_ok=True)
    
    # Using Adoptium's API to fetch latest Temurin JDK 17 for macOS x64
    url = "https://api.adoptium.net/v3/binary/latest/17/ga/mac/x64/jdk/hotspot/normal/eclipse"
    tar_path = os.path.join(jdk_dir, "openjdk.tar.gz")
    
    print(f"Downloading portable OpenJDK from {url}...")
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req) as response:
            with open(tar_path, 'wb') as out_file:
                out_file.write(response.read())
        print("Download complete. Extracting tar.gz...")
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=jdk_dir)
        os.remove(tar_path)
        print("Extraction complete.")
    except Exception as e:
        print(f"Failed to download/extract JDK: {e}")
        if os.path.exists(tar_path):
            os.remove(tar_path)
        return None
        
    java_bin = find_java_binary(jdk_dir)
    if java_bin:
        print(f"Java successfully set up at: {java_bin}")
    else:
        print("Could not find java binary in extracted contents.")
    return java_bin

def find_java_binary(base_dir):
    # Recursively search for 'bin/java' or 'Contents/Home/bin/java'
    for root, dirs, files in os.walk(base_dir):
        if "java" in files:
            path = os.path.join(root, "java")
            # Ensure it is executable
            if os.access(path, os.X_OK):
                return root
    return None

if __name__ == "__main__":
    download_and_extract_java()
