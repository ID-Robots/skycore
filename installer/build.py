import os
import tarfile
import sys

def create_tar_gz(archive_name, files):
    try:
        with tarfile.open(archive_name, "w:gz") as tar:
            for file in files:
                if os.path.isfile(file):
                    tar.add(file)
                    print(f"Added '{file}' to '{archive_name}'.")
                else:
                    print(f"Error: '{file}' does not exist and was not added.")
        print(f"\nArchive '{archive_name}' created successfully.")
    except Exception as e:
        print(f"An error occurred while creating the archive: {e}")

def main():
    
    # Define the files to be compressed
    files_to_compress = ['skycore.sh', 'skycore_cli.py']
    
    # Define the name of the archive
    archive_name = 'skycore.tar.gz'
    
    # Optional: Check if at least one file exists before proceeding
    existing_files = [file for file in files_to_compress if os.path.isfile(file)]
    
    if not existing_files:
        print("Error: None of the specified files exist. Exiting.")
        sys.exit(1)
    
    # Create the tar.gz archive
    create_tar_gz(archive_name, files_to_compress)

if __name__ == "__main__":
    main()
