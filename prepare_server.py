import os
import zipfile

def create_server_zip():
    target_zip = "utcoder_server.zip"
    
    # Thư mục và file cần đưa vào zip
    include_dirs = ["core", "ui"]
    include_files = [
        "main.py", "server.py", "config.server.json", "docker-compose.server.yml", 
        "Dockerfile", "requirements.txt", "uninstall.sh", "DEPLOYMENT.md"
    ]

    # Các pattern cần bỏ qua
    exclude_patterns = ["__pycache__", ".pytest_cache", "chroma_db", ".git"]

    print(f"Creating {target_zip}...")
    
    with zipfile.ZipFile(target_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Xử lý các thư mục
        for d in include_dirs:
            if not os.path.exists(d):
                continue
            for root, dirs, files in os.walk(d):
                # Loại bỏ các thư mục không cần thiết
                dirs[:] = [d_name for d_name in dirs if d_name not in exclude_patterns]
                
                for file in files:
                    if file.endswith(('.pyc', '.pyo')):
                        continue
                    file_path = os.path.join(root, file)
                    # Ghi vào zip, arcname là đường dẫn tương đối
                    zf.write(file_path, arcname=file_path)

        # Xử lý các file riêng lẻ
        for f in include_files:
            if os.path.exists(f):
                arcname = f
                # Tự động đổi tên khi nén vào zip
                if f == "config.server.json":
                    arcname = "config.json"
                elif f == "docker-compose.server.yml":
                    arcname = "docker-compose.yml"
                    
                zf.write(f, arcname=arcname)

    print(f"Done! Server package is ready: {os.path.abspath(target_zip)}")
    print("You can now copy the 'utcoder_server.zip' file to your Ubuntu server.")

if __name__ == "__main__":
    create_server_zip()
