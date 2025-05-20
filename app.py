"""
    Web application to process Refinitiv WorldCheck reports
    Copyright (C) 2023 Yingyi Zhao

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
from flask import Flask, request, render_template, redirect, url_for, send_file, flash, jsonify, after_this_request, Response, stream_with_context, session
from werkzeug.utils import secure_filename
from main import __main__, cleanup_directory, allowed_file
from authlib.integrations.flask_client import OAuth
import os
import requests
import boto3
from functools import wraps
import logging

app = Flask(__name__)
app.secret_key = '147d98b80bc9e3164f5ba8108db59a07'  # Set a secret key for security purposes
#app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()  # Temporary directory for uploads
app.config['UPLOAD_FOLDER'] = '/tmp' # Use /tmp directory which is writable in App Engine
ALLOWED_EXTENSIONS = {'pdf'}

# Add at the start of your app
temp_dir = '/tmp/worldcheck_uploads'
app.config['UPLOAD_FOLDER'] = temp_dir

# Ensure the directory exists and is writable
try:
    os.makedirs(temp_dir, mode=0o777, exist_ok=True)
except Exception as e:
    logging.error(f"Failed to create temp directory: {e}")
    raise

# Initialize OAuth
oauth = OAuth(app)

# AWS Cognito Configuration
AWS_COGNITO_CONFIG = {
    "region": "us-east-2",
    "user_pool_id": "us-east-2_KMV99nFc1",
    "client_id": "2704pqi0p24dee1s8qe5at2j7i",
    #"callback_url": os.getenv('COGNITO_CALLBACK_URL', 'http://localhost:8080'),
    "callback_url": os.getenv('COGNITO_CALLBACK_URL', 'https://kyc.smartibd.com'),
    "domain": "us-east-2kmv99nfc1.auth.us-east-2.amazoncognito.com"  # Keep original domain format
}

# Register Cognito OIDC client
oauth.register(
    name='oidc',
    server_metadata_url=f'https://cognito-idp.{AWS_COGNITO_CONFIG["region"]}.amazonaws.com/{AWS_COGNITO_CONFIG["user_pool_id"]}/.well-known/openid-configuration',
    authority=f'https://cognito-idp.{AWS_COGNITO_CONFIG["region"]}.amazonaws.com/{AWS_COGNITO_CONFIG["user_pool_id"]}/',
    client_id=AWS_COGNITO_CONFIG['client_id'],
    client_kwargs={
        'scope': 'openid email phone',
        'redirect_uri': AWS_COGNITO_CONFIG['callback_url']
    },
)

# Ensure the upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Add before app initialization
logging.basicConfig(level=logging.INFO)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    temp_dir = app.config['UPLOAD_FOLDER']
    cleanup_directory(temp_dir)
    return render_template('index.html', files=[], files_uploaded=False)

@app.route('/login')
def login():
    # Use the configured callback URL from Cognito settings
    return oauth.oidc.authorize_redirect(f"{AWS_COGNITO_CONFIG['callback_url']}/auth")

@app.route('/auth')
def authorize():
    print("authorize")
    try:
        token = oauth.oidc.authorize_access_token()
        userinfo = token.get('userinfo')
        if userinfo:
            session['user'] = userinfo
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Authorization error: {str(e)}")
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
#@login_required
def upload_file():
    uploaded_files = []
    logging.info(f"Upload directory: {app.config['UPLOAD_FOLDER']}")
    
    if 'file' not in request.files:
        logging.warning("No file part in request")
        return jsonify({'success': False, 'error': 'No file part'})
    
    files = request.files.getlist('file')
    
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                file.save(file_path)
                logging.info(f"Successfully saved file: {filename}")
                uploaded_files.append(filename)
            except Exception as e:
                logging.error(f"Failed to save file {filename}: {e}")
                return jsonify({'success': False, 'error': f'Failed to save file: {str(e)}'})
    
    if not uploaded_files:
        return jsonify({'success': False, 'error': 'No valid files uploaded'})
    
    return jsonify({
        'success': True,
        'files': uploaded_files
    })

@app.route('/run_main', methods=['POST'])
def run_main():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Login required'}), 401
    
    temp_dir = app.config['UPLOAD_FOLDER']
    rename_option = request.form.get('rename', 'no')
    __main__(temp_dir, rename=rename_option)
    return redirect(url_for('download_compressed_files'))

@app.route('/remove_file', methods=['POST'])
def remove_file():
    data = request.json
    file_name = data.get('file')
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
    if os.path.exists(file_path):
        os.remove(file_path)
    return '', 204

@app.route('/downloads')
def download_compressed_files():
    try:
        temp_dir = app.config['UPLOAD_FOLDER']
        zip_file_path = os.path.join(temp_dir, 'finished.zip')

        if os.path.exists(zip_file_path) and os.path.getsize(zip_file_path) < 7 * 1024:  # 7kb in bytes
            cleanup_directory(temp_dir)
            flash('程序发生了未知错误，请重试', 'warning')  # Flash a message
            return redirect('/')  # Redirect to another route/page
        
        return redirect(url_for('download_page'))

    except Exception as e:
        print(f"Error in download_compressed_files: {e}")
        return "An error occurred", 500

@app.route('/download_page')
def download_page():
    return render_template('download.html')  # Renders the intermediate HTML page

@app.route('/download_stream')
def download_stream():
    try:
        temp_dir = app.config['UPLOAD_FOLDER']
        zip_file_path = os.path.join(temp_dir, 'finished.zip')

        # Check if the file exists
        if not os.path.exists(zip_file_path):
            # Handle the missing file scenario
            # Clean up the remaining files
            cleanup_directory(temp_dir)
            flash('程序发生了未知错误，请重试', 'error')
            return redirect('/')

        # Function to stream the file
        def generate():
            with open(zip_file_path, 'rb') as fzip:
                yield from fzip  # Stream the file
            os.remove(zip_file_path)  # Delete the zip file after sending

            # Clean up the remaining files
            for root, dirs, file_names in os.walk(temp_dir, topdown=False):
                for file_name in file_names:
                    os.remove(os.path.join(root, file_name))
                for dir_name in dirs:
                    os.rmdir(os.path.join(root, dir_name))

        return Response(stream_with_context(generate()), mimetype='application/zip', headers={'Content-Disposition': 'attachment; filename=finished.zip'})

    except Exception as e:
        print(f"Error in download_stream: {e}")
        return "An error occurred", 500

# Add after app initialization
@app.errorhandler(500)
def server_error(e):
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500

@app.errorhandler(502)
def gateway_error(e):
    logging.exception('Gateway error occurred.')
    return 'Bad gateway error occurred.', 502
    
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)  # Set debug=False in production

'''
FLASK
Copyright 2010 Pallets

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''

'''
PDFPLUMBER
Copyright (c) 2015, Jeremy Singer-Vine

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

'''
PANDAS
Copyright (c) 2008-2011, AQR Capital Management, LLC, Lambda Foundry, Inc. and PyData Development Team
All rights reserved.

Copyright (c) 2011-2023, Open source contributors.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''

'''
XLSXWRITER
Copyright (c) 2013-2023, John McNamara <jmcnamara@cpan.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''