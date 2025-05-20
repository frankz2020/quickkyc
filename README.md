# QuickKYC - WorldCheck Report Processor

A web application for processing Refinitiv WorldCheck reports, automating the extraction and organization of compliance data.

## Features

- Process WorldCheck PDF reports and categorize them into three types:
  - FOUND: Reports with confirmed matches
  - NO: Reports with no matches
  - CASE: Reports requiring further review
- Extract and organize data into Excel format
- Automatic file renaming based on report content
- Secure authentication via AWS Cognito
- Support for both individual and company reports

## Prerequisites

- Python 3.7+
- pip (Python package manager)
- AWS Cognito account and configuration

## Installation

1. Clone the repository:
```bash
git clone [repository-url]
cd quickkyc
```

2. Create and activate a virtual environment:
```bash
# Windows
python -m venv flask_app
flask_app\Scripts\activate

# Linux/Mac
python3 -m venv flask_app
source flask_app/bin/activate
```

3. Install required packages:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with the following content:
```env
# Flask Environment
FLASK_ENV=development
FLASK_APP=app.py

# AWS Cognito Configuration
COGNITO_REGION=us-east-2
COGNITO_USER_POOL_ID=your_user_pool_id
COGNITO_CLIENT_ID=your_client_id
COGNITO_DOMAIN=your_cognito_domain

# Callback URLs
DEV_CALLBACK_URL=http://localhost:8080
PROD_CALLBACK_URL=https://your-production-domain.com

# Flask Secret Key
FLASK_SECRET_KEY=your_secret_key

# Upload Directory
UPLOAD_FOLDER=/tmp/worldcheck_uploads
```

## Usage

1. Start the development server:
```bash
flask run --port=8080
```

2. Access the application at `http://localhost:8080`

3. Log in using your AWS Cognito credentials

4. Upload WorldCheck PDF reports

5. Click "Process Documents" to:
   - Rename files based on content
   - Extract and organize data
   - Generate Excel report
   - Create downloadable ZIP archive

## Environment Configuration

The application supports two environments:

### Development
- Set `FLASK_ENV=development` in `.env`
- Uses localhost callback URL
- Debug mode enabled

### Production
- Set `FLASK_ENV=production` in `.env`
- Uses production callback URL
- Debug mode disabled

## Output Files

- `finished.xlsx`: Excel file containing:
  - Individual Name sheet: Personal data and matches
  - Company Name sheet: Company data and matches
- `finished.zip`: Archive containing:
  - Renamed PDF files
  - Excel report
  - Processing logs

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.

## Dependencies

- Flask: Web framework
- pdfplumber: PDF text extraction
- pandas: Data manipulation
- xlsxwriter: Excel file generation
- authlib: OAuth authentication
- python-dotenv: Environment variable management

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request