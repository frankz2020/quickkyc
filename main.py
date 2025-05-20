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
import zipfile
import os
import pdfplumber
import re
import pandas as pd


ALLOWED_EXTENSIONS = {'pdf'}

class CaseReport:
    def __init__(self, pdf_file_path):
        self.pdf_file_path = pdf_file_path
        self.text = None
        self.should_process = True
        self.extracted_data = {}  # Store all extracted data in one place
        self.file_name = os.path.basename(pdf_file_path)  # Initialize with original filename
        
        # Only do initial screening, defer full text extraction
        with pdfplumber.open(pdf_file_path) as pdf:
            # Only read first page for screening
            first_page = pdf.pages[0].extract_text() or ""
            if "WORLD-CHECK" not in first_page:
                self.should_process = False

    def _extract_text_if_needed(self):
        """Lazy load text only when needed"""
        if self.text is None and self.should_process:
            print(f"\nDebug: Attempting text extraction")
            print(f"Debug: should_process = {self.should_process}")
            print(f"Debug: pdf_file_path = {self.pdf_file_path}")
            
            try:
                with pdfplumber.open(self.pdf_file_path) as pdf:
                    print(f"Debug: Successfully opened PDF with {len(pdf.pages)} pages")
                    pages_text = []
                    for i, page in enumerate(pdf.pages):
                        try:
                            text = page.extract_text() or ""
                            pages_text.append(text)
                            print(f"Debug: Page {i+1} extracted {len(text)} characters")
                            
                            # Debug: Print first occurrence of "Name" in each page
                            name_index = text.find("Name")
                            if name_index != -1:
                                context = text[max(0, name_index-50):min(len(text), name_index+100)]
                                print(f"Debug: Found 'Name' on page {i+1} with context:\n{context}\n")
                            
                        except Exception as e:
                            print(f"Debug: Error on page {i+1}: {str(e)}")
                    
                    self.text = "\n".join(pages_text)
                    print(f"Debug: Total text length: {len(self.text) if self.text else 0}")
                
                    # Store the text temporarily
                    temp_text = self.text
                    
                    # Extract all needed data
                    self._extract_all_data()
                    
                    # Restore the text for sort_type to use
                    self.text = temp_text
                
            except Exception as e:
                print(f"Debug: Failed to open PDF: {str(e)}")
                self.text = None
                return

    def _extract_all_data(self):
        """Extract all needed data in one pass through the text"""
        # First determine the report type
        if "WORLD-CHECK MATCH DETAILS REPORT" in self.text:
            # FOUND report format
            in_section = False
            name_section_lines = []
            for line in self.text.split('\n'):
                if "CASE AND COMPARISON DATA" in line:
                    in_section = True
                    continue
                if in_section and "KEY DATA" in line:
                    break
                if in_section and "World-Check Data" in line:
                    continue
                if in_section:
                    name_section_lines.append(line)
                    
            for line in name_section_lines:
                if 'Name' in line:
                    self.extracted_data['name_data_pair'] = line
                    break
                
        elif "CASE REPORT" in self.text:
            # CASE report format - simpler structure
            for line in self.text.split('\n'):
                if 'Name' in line and len(line.strip().split()) >= 2:  # Ensure there's a name after "Name"
                    self.extracted_data['name_data_pair'] = line
                    break

        # Extract biography and reports if needed
        biography_indices = [m.start() for m in re.finditer("BIOGRAPHY", self.text)]
        if len(biography_indices) >= 2:
            reports_index = self.text.find("REPORTS")
            identification_index = self.text.find("IDENTIFICATION")
            
            if reports_index != -1 and identification_index != -1:
                self.extracted_data['bio_info'] = self.text[biography_indices[1] + len("BIOGRAPHY"):reports_index].strip()
                self.extracted_data['report_info'] = self.text[reports_index + len("REPORTS"):identification_index].strip()

        # Add entity type detection
        self.extracted_data['entity_type'] = self._detect_entity_type()

    def _detect_entity_type(self):
        """
        Detect whether the entity is an individual or organization using multiple indicators
        Returns: "individual" or "organization"
        """
        indicators = {
            'individual': 0,
            'organization': 0
        }
        
        # Check for common organization indicators in name
        org_keywords = {'limited', 'ltd', 'llc', 'inc', 'corporation', 'corp', 'company', 'co', 
                       'group', 'holdings', 'bank', '公司', '集团', '银行', '企业', '有限'}
        
        name = self.extracted_data.get('name_data_pair', '').lower()
        if any(keyword in name.lower() for keyword in org_keywords):
            indicators['organization'] += 2

        # Look for personal identifiers in the text
        personal_identifiers = {
            'date of birth': 3,
            'nationality': 2, 
            'passport': 2,
            'gender': 2,
            'birth place': 2,
            'place of birth': 2,
            '出生': 2,
            '国籍': 2,
            '护照': 2,
            '性别': 2
        }
        
        # Search in first 1000 characters to avoid false positives
        text_sample = self.text[:1000].lower() if self.text else ''
        for identifier, weight in personal_identifiers.items():
            if identifier in text_sample:
                indicators['individual'] += weight

        # Check for organization identifiers
        org_identifiers = {
            'registration number': 2,
            'registered address': 2,
            'business type': 2,
            'incorporation date': 2,
            'registered capital': 2,
            '注册号': 2,
            '注册地址': 2,
            '企业类型': 2,
            '注册资本': 2
        }
        
        for identifier, weight in org_identifiers.items():
            if identifier in text_sample:
                indicators['organization'] += weight

        # Make the classification decision
        if indicators['individual'] > indicators['organization']:
            return "individual"
        elif indicators['organization'] > indicators['individual']:
            return "organization"
        else:
            # If tied, default to individual as it's more common
            return "individual"

    @staticmethod
    def is_chinese(char):
        """Check if a character is a Chinese character."""
        return '\u4e00' <= char <= '\u9fff'

    def extract_chinese_name(self, name_string):
        """Extract the Chinese characters from the name string."""
        blocks = name_string.split(' ')
        for name in blocks:
            if self.is_chinese(name[0]):
                return name
        return ''.join([char for char in name_string if self.is_chinese(char)])

    def rename_no(self, upload_folder):
        self._extract_text_if_needed()
        if 'name_data_pair' not in self.extracted_data:
            return

        name_data_pair = self.extracted_data['name_data_pair']
        print(f"Selected data pair: {name_data_pair}")

        chinese_name = self.extract_chinese_name(name_data_pair)

        if chinese_name:
            self.extracted_data['extracted_name'] = chinese_name
            prefix = "No"
        else:
            name_start_index = name_data_pair.index("Name") + len("Name")
            self.extracted_data['extracted_name'] = name_data_pair[name_start_index:].strip()
            prefix = "No "

        new_file_name = f"{prefix}{self.extracted_data['extracted_name']}.pdf"

        # Use the temporary folder path
        new_file_path = os.path.join(upload_folder, new_file_name)
        self.file_name = new_file_name

        try:
            # Update the original file path for renaming
            original_file_path = os.path.join(upload_folder, os.path.basename(self.pdf_file_path))
            os.rename(original_file_path, new_file_path)
            print(f"PDF file renamed to: {new_file_name}")
        except OSError as e:
            print(f"Failed to rename the file: {e}")

    def extract_name(self):
        self._extract_text_if_needed()
        if 'name_data_pair' not in self.extracted_data:
            return None

        name_data_pair = self.extracted_data['name_data_pair']
        print(f"Selected data pair: {name_data_pair}")

        chinese_name = self.extract_chinese_name(name_data_pair)

        if chinese_name:
            extracted_name = chinese_name
            print(extracted_name)
            self.extracted_data['extracted_name'] = extracted_name
            return extracted_name
        else:
            name_start_index = name_data_pair.index("Name") + len("Name")
            extracted_name = name_data_pair[name_start_index:].strip()
            print(extracted_name)
            self.extracted_data['extracted_name'] = extracted_name
            return extracted_name

    def rename_found(self, upload_folder):
        # Extract the name
        self.extract_name()

        # Check if a name was extracted
        if not self.extracted_data['extracted_name']:
            print("No name extracted. Cannot rename the document.")
            return

        # Generate the new filename
        base_name = self.extracted_data['extracted_name']
        count = 1
        new_file_name = f"{base_name}{count:02d}.pdf"
        new_file_path = os.path.join(upload_folder, new_file_name)

        while os.path.exists(new_file_path):
            count += 1
            new_file_name = f"{base_name}{count:02d}.pdf"
            new_file_path = os.path.join(upload_folder, new_file_name)
        self.file_name = new_file_name

        # Rename the document
        try:
            # Update the original file path to the temporary folder path
            original_file_path = os.path.join(upload_folder, os.path.basename(self.pdf_file_path))
            os.rename(original_file_path, new_file_path)
            self.pdf_file_path = new_file_path
            print(f"Document renamed to: {new_file_name}")

        except OSError as e:
            print(f"Failed to rename the document: {e}")

    def read_details(self):
        # Ensure text is extracted first
        self._extract_text_if_needed()
        
        # Check if text extraction was successful
        if not self.text:
            print("Failed to extract text from PDF.")
            return

        # Check if text from the second page exists
        if len(self.text) < 2:
            print("Insufficient pages to extract details.")
            return

        # Find the indices of the required titles
        biography_indices = [m.start() for m in re.finditer("BIOGRAPHY", self.text)]
        reports_index = self.text.find("REPORTS")
        identification_index = self.text.find("IDENTIFICATION")

        # Ensure we have at least two occurrences of "BIOGRAPHY" and "REPORTS"
        if len(biography_indices) < 2 or reports_index == -1 or identification_index == -1:
            print("Unable to extract details.")
            return

        # Extract the desired text
        extracted_text1 = self.text[biography_indices[1] + len("BIOGRAPHY"):reports_index].strip().replace("\n", " ")
        extracted_text2 = self.text[reports_index + len("REPORTS"):identification_index].strip().replace("\n", " ")

        print("Extracted Text 1:")
        print(extracted_text1)
        print("Extracted Text 2:")
        print(extracted_text2)

        # Optionally, you can assign the extracted text to instance variables for later use
        self.extracted_data['bio_info'] = extracted_text1
        self.extracted_data['report_info'] = extracted_text2

    def rename_case(self, upload_folder):
        self._extract_text_if_needed()
        if 'name_data_pair' not in self.extracted_data:
            print("Debug: No name_data_pair found in extracted_data")  # Add debug print
            return

        name_data_pair = self.extracted_data['name_data_pair']
        print(f"Selected data pair: {name_data_pair}")  # Add debug print

        chinese_name = self.extract_chinese_name(name_data_pair)

        if chinese_name:
            self.extracted_data['extracted_name'] = chinese_name
            suffix = "Case"
        else:
            name_start_index = name_data_pair.index("Name") + len("Name")
            self.extracted_data['extracted_name'] = name_data_pair[name_start_index:].strip()
            suffix = "Case "

        # Get the new file name
        new_file_name = f"{self.extracted_data['extracted_name']}{suffix}.pdf"
        print(f"Attempting to rename to: {new_file_name}")  # Add debug print

        # Use the temporary folder path from app.config
        new_file_path = os.path.join(upload_folder, new_file_name)
        self.file_name = new_file_name

        try:
            # Update the original file path for renaming
            original_file_path = os.path.join(upload_folder, os.path.basename(self.pdf_file_path))
            print(f"Renaming from {original_file_path} to {new_file_path}")  # Add debug print
            os.rename(original_file_path, new_file_path)
            print(f"PDF file renamed to: {new_file_name}")
        except OSError as e:
            print(f"Failed to rename the file: {e}")

    def sort_type(self):
        # First ensure text is extracted
        print(f"\nStarting sort_type for file: {self.file_name}")
        print("Before _extract_text_if_needed, self.text is:", "None" if self.text is None else "Present")
        
        self._extract_text_if_needed()
        
        print("After _extract_text_if_needed, self.text is:", "None" if self.text is None else f"Present ({len(self.text)} chars)")
        
        if not self.text:  # Add safety check
            print(f"Warning: Could not extract text from PDF: {self.file_name}")
            return "NO"
        
        # Debug prints for pattern matching
        print("\nSearching for key patterns:")
        print(f"'WORLD-CHECK MATCH DETAILS REPORT' found: {'WORLD-CHECK MATCH DETAILS REPORT' in self.text}")
        print(f"'CASE REPORT' found: {'CASE REPORT' in self.text}")
        
        result = "NO"  # Default result
        
        if "WORLD-CHECK MATCH DETAILS REPORT" in self.text:
            print("Identified as: FOUND")
            result = "FOUND"
        elif "CASE REPORT" in self.text:
            pattern = r"Unresolved Matches (\d+)"
            print("\nSearching for 'Unresolved Matches' pattern...")
            
            match = re.search(pattern, self.text)
            print(f"Pattern match found: {bool(match)}")
            
            if match:
                total_matches = int(match.group(1))
                print(f"Number of unresolved matches: {total_matches}")
                if total_matches > 0:
                    print("Identified as: CASE")
                    result = "CASE"
                else:
                    print("Identified as: NO (0 matches)")
        else:
            print("Identified as: NO (no matching report type)")
        
        # Clear text if we don't need it for other operations
        if not any(key in ['bio_info', 'report_info'] for key in self.extracted_data):
            print("Debug: Clearing text from memory")
            self.text = None
        
        return result
      
def batch_rename_sort(temp_dir,reports_dict):

    for pdf_file_path, report in reports_dict.items():
        if pdf_file_path.endswith(".pdf"):
            print(f"\nProcessing file: {pdf_file_path}")  # Debug print

            if not report.should_process:
                print("Skipping file - should not process")  # Debug print
                continue  # Skip the rest of the loop and don't process this file

            report_type = report.sort_type()
            print(f"Report type identified as: {report_type}")  # Debug print

            if report_type == "FOUND":
                print("Renaming as FOUND")  # Debug print
                report.rename_found(temp_dir)
            elif report_type == "NO":
                print("Renaming as NO")  # Debug print
                report.rename_no(temp_dir)
            elif report_type == "CASE":
                print("Renaming as CASE")  # Debug print
                report.rename_case(temp_dir)
            else:
                file_name = os.path.basename(pdf_file_path)
                print(f"Unable to rename {file_name}")  # Debug print

def organize_data(reports_dict):
    data = {
        'filenames':[],
        'names':[],
        'position':[],
        'exist':[],
        'reports':[],
        'bios':[],
        'real':[],
        'reason':[],
        'verifier':[]
    }

    data_company = {
        'filenames':[],
        'names':[],
        'relationship':[],
        'exist':[],
        'reports':[],
        'real':[],
        'reason':[],
        'verifier':[]
    }

    for pdf_file_path, report in reports_dict.items():
        # Skip if the report shouldn't be processed
        if not report.should_process:
            print(f"Skipping {pdf_file_path} - not a valid WorldCheck report")
            continue

        # Initialize file_name if not set
        if not hasattr(report, 'file_name') or report.file_name is None:
            report.file_name = os.path.basename(pdf_file_path)
            
        if report.file_name.endswith(".pdf") and "CaseD" not in report.file_name:
            # Get report type to determine existence
            report_type = report.sort_type()
            
            # Skip CASE type reports
            if report_type == "CASE":
                print(f"Skipping {report.file_name} - CASE type report")
                continue
                
            exists = '是' if report_type == "FOUND" else '否'
            
            try:
                report.read_details()
                report.extract_name()
            except Exception as e:
                print(f"Error processing {report.file_name}: {str(e)}")
                continue

            # Use the entity type detection
            if report.extracted_data.get('entity_type') == "individual":
                data['filenames'].append(report.file_name.replace('.pdf',''))
                data['names'].append(report.extracted_data.get('extracted_name', ''))
                
                # For NO type reports, use empty strings for bio and report info
                if report_type == "NO":
                    data['reports'].append('')
                    data['bios'].append('')
                else:  # FOUND type
                    try:
                        report_info = report.extracted_data.get('report_info')
                        bio_info = report.extracted_data.get('bio_info')
                        
                        if not report_info:
                            print(f"Warning: No report info found for {report.file_name}")
                        if not bio_info:
                            print(f"Warning: No bio info found for {report.file_name}")
                            
                        data['reports'].append(report_info if report_info else 'CHECK DATA')
                        data['bios'].append(bio_info if bio_info else 'CHECK DATA')
                    except Exception as e:
                        print(f"Error extracting report/bio info for {report.file_name}: {str(e)}")
                        data['reports'].append("CHECK DATA")
                        data['bios'].append("CHECK DATA")

                data['exist'].append(exists)
                data['position'].append('')
                data['real'].append('')
                data['reason'].append('')
                data['verifier'].append('')

            else:  # organization
                data_company['filenames'].append(report.file_name.replace('.pdf',''))
                data_company['names'].append(report.extracted_data.get('extracted_name', ''))
                
                # For NO type reports, use empty strings for report info
                if report_type == "NO":
                    data_company['reports'].append('')
                else:  # FOUND type
                    try:
                        report_info = report.extracted_data.get('report_info')
                        if not report_info:
                            print(f"Warning: No report info found for company {report.file_name}")
                        data_company['reports'].append(report_info if report_info else 'CHECK DATA')
                    except Exception as e:
                        print(f"Error extracting report info for company {report.file_name}: {str(e)}")
                        data_company['reports'].append("CHECK DATA")

                data_company['exist'].append(exists)
                data_company['relationship'].append('')
                data_company['real'].append('')
                data_company['reason'].append('')
                data_company['verifier'].append('')

    return data, data_company

def export_as_excel(data, data_company, upload_folder):
    
    column_names = ['World Check文件名','姓名','职位','验证存在','负面信息','政治人物 (PEP) 资料','是否本人','判断依据','审核人']
    dataframe_ind = pd.DataFrame.from_dict(data)
    dataframe_ind.columns = column_names
    dataframe_ind = dataframe_ind.sort_values(by=['姓名','World Check文件名'])

    column_names = ['World Check文件名','公司名称','与客户的关系','验证存在','负面信息','是否公司','判断依据','审核人']
    dataframe_com = pd.DataFrame.from_dict(data_company)
    dataframe_com.columns = column_names
    dataframe_com = dataframe_com.sort_values(by=['公司名称','World Check文件名'])

    excel_file_path = os.path.join(upload_folder, "finished.xlsx")

    # Saving the dataframes to Excel
    with pd.ExcelWriter(excel_file_path, engine="xlsxwriter") as writer:
        dataframe_ind.to_excel(writer, sheet_name="Individual Name", index=False)
        dataframe_com.to_excel(writer, sheet_name="Company Name", index=False)

    print(f"Excel file exported to: {excel_file_path}")

def __main__(temp_dir, rename='yes'):
    reports_dict = {}
    skipped_files = []

    # Create CaseReport instances for each PDF file and store in the dictionary
    for file_name in os.listdir(temp_dir):
        if file_name.endswith(".pdf"):
            pdf_file_path = os.path.join(temp_dir, file_name)
            report = CaseReport(pdf_file_path)

            if report.should_process:
                reports_dict[pdf_file_path] = report
            else:
                skipped_files.append(file_name)
    
    # Determine and delete skipped files
    for file_name in skipped_files:
        skipped_file_path = os.path.join(temp_dir, file_name)
        if os.path.exists(skipped_file_path):
            os.remove(skipped_file_path)

    if rename == 'yes':
        batch_rename_sort(temp_dir, reports_dict)
    
    data_individual, data_company = organize_data(reports_dict)
    export_as_excel(data_individual, data_company, temp_dir)

    zip_file_path = os.path.join(temp_dir, 'finished.zip')
    with zipfile.ZipFile(zip_file_path, 'w') as zipf:
        for root, dirs, file_names in os.walk(temp_dir):
            for file_name in file_names:
                if file_name == 'finished.zip':
                    continue  # Skip the zip file itself
                file_path = os.path.join(root, file_name)
                zipf.write(file_path, arcname=os.path.relpath(file_path, start=temp_dir))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_directory(directory):
    for root, dirs, file_names in os.walk(directory, topdown=False):
        for file_name in file_names:
            try:
                os.remove(os.path.join(root, file_name))
            except Exception as e:
                print(f"Error removing file {file_name}: {e}")
        for dir_name in dirs:
            try:
                os.rmdir(os.path.join(root, dir_name))
            except Exception as e:
                print(f"Error removing directory {dir_name}: {e}")

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