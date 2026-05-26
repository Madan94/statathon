import http.server
import os

PORT = 8080
TEST_DATA_DIR = "test_data"
MOCK_CSV_PATH = os.path.join(TEST_DATA_DIR, "mock_mospi.csv")
CSV_CONTENT = "nic_2008,maternal_mort_rt,dist_cd,hh_size,quarter\n0111,12.5,45,4,Q1\n0112,11.2,46,5,Q2\n"

def setup_mock_data():
    """Create the test_data directory and write the mock CSV file."""
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    with open(MOCK_CSV_PATH, "w", encoding="utf-8") as f:
        f.write(CSV_CONTENT)

class MockS3Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        """Intercept GET requests to simulate presigned URL authorization."""
        if "X-Amz-Signature" in self.path or "token=" in self.path:
            # Presigned URL / token is valid, serve the mock CSV
            self.send_response(200)
            self.send_header("Content-type", "text/csv")
            self.end_headers()
            with open(MOCK_CSV_PATH, "rb") as f:
                self.wfile.write(f.read())
        else:
            # Missing authorization token, reject request
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"403 Forbidden: Missing presigned URL token/signature")

def run():
    setup_mock_data()
    
    # Allow port reuse to prevent "Address already in use" errors during dev restarts
    class ReusableServer(http.server.HTTPServer):
        allow_reuse_address = True

    server_address = ("127.0.0.1", PORT)
    httpd = ReusableServer(server_address, MockS3Handler)
    
    mock_url = f"http://localhost:{PORT}/stream?token=statathon_secure_token_123"
    print(f"Starting mock S3 ingress server on port {PORT}...")
    print(f"Target mock presigned URL: {mock_url}")
    print("Press Ctrl+C to stop")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == "__main__":
    run()
