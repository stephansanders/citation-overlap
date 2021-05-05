/**
 * Citation Overlap Google Apps Script Add-On
 * Stephan Sanders Lab, 2020, 2021
 */

// database names
DB_NAMES = [
  'medline',
  'embase',
  'scopus'
];

// name of sheet with database overlaps
SHEET_OVERLAPS = 'overlaps';

// maximum column width
MAX_COL_WIDTH = 300;

/**
 * Add a custom menu when the user opens the spreadsheet.
 */
function onOpen(e) {
  var menu = SpreadsheetApp.getUi().createAddonMenu();
  menu.addItem('Show sidebar', 'showSidebar');
  menu.addItem('Set up sheets', 'setupSheets');
  menu.addItem('Find overlaps', 'findOverlaps');
  menu.addItem('Resize processed columns', 'resizeColumns');
  menu.addItem('Remove processed sheets', 'clearSheets');
//  if (e && e.authMode == ScriptApp.AuthMode.NONE) {
//  } else {
//    // TODO: add functionality requiring authoriziation
//  }
  menu.addToUi();
}

function showSidebar() {
  var html = HtmlService.createTemplateFromFile("Sidebar").evaluate();
  html.setTitle("Citation-Overlap");
  SpreadsheetApp.getUi().showSidebar(html);
}

/**
 * Includes additional files, such as CSS and JS files.
 * @param {string} filename file to include
 * @return {HtmlOutput} html output
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename)
      .setSandboxMode(HtmlService.SandboxMode.IFRAME)
      .getContent();
}

/**
 * Set up empty sheets with database names.
 */
function setupSheets() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var namesLen = DB_NAMES.length;
  for (var i = 0; i < namesLen; i++) {
    spreadsheet.insertSheet(DB_NAMES[i], i);
  }
  spreadsheet.setActiveSheet(spreadsheet.getSheetByName(DB_NAMES[0]));
}

/**
 * Get processed sheets as identified by suffix or as the overlaps sheet.
 *
 * @return Array of processed sheets.
 */
function getProcessedSheets() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = spreadsheet.getSheets();
  var sheetsLen = sheets.length;
  var sheetsProc = [];
  // find all sheets with "clean" suffix and the overlaps sheet
  for (var i = 0; i < sheetsLen; i++) {
    var sheet = sheets[i];
    var name = sheet.getName()
    if (name.endsWith('_clean') || name === SHEET_OVERLAPS) {
      sheetsProc.push(sheet);
    }
  }
  return sheetsProc;
}

/**
 * Clear processed sheets.
 */
function clearSheets() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = getProcessedSheets();
  var sheetsLen = sheets.length;
  for (var i = 0; i < sheetsLen; i++) {
    spreadsheet.deleteSheet(sheets[i]);
  }
}

/**
 * Pass sheets with database information to web server for extraction and
 * finding overlaps across databases.
 *
 * Wrap up database sheets into JSON payload for server. Accept response
 * as JSON and parse into separate sheets, with one sheet for each
 * database and a separate sheet for the overlaps.
 */
function findOverlaps() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = spreadsheet.getSheets();
  var sheetsLen = sheets.length;
  var namesLen = DB_NAMES.length;
  
  // convert database sheets to CSV strings
  var data = {};
  for (var i = 0; i < sheetsLen; i++) {
    var sheet = sheets[i];
    var sheetName = sheet.getName();
    for (var j = 0; j < namesLen; j++) {
      if (sheetName.startsWith(DB_NAMES[j])) {
        csv = convertRangeToCsvStr(sheet);
        Logger.log("sheet " + sheetName)
        data[sheetName] = csv;
        break;
      }
    }
  }
  
  // send database string data to server
  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(data)
  };
  //Logger.log("options: " + options["payload"]);
  var response = UrlFetchApp.fetch(
    PropertiesService.getScriptProperties().getProperty('SERVER_URL'), options);
  
  // insert sheets for server response after database sheets and in their
  // same order, with overlaps sheet at end; assume response keys are
  // same as payload except additional overlaps
  var json = response.getContentText()
  //Logger.log("response: " + json);
  var respData = JSON.parse(json);
  var respDataLen = respData.length;
  var namesOv = Object.keys(data);
  namesOv.push(SHEET_OVERLAPS);
  var namesOvLen = namesOv.length;
  for (var i = 0; i < namesOvLen; i++) {
    var key = namesOv[i]
    var val = respData[key];
    Logger.log("key: " + key + ", val: " + val.slice(-200));
    var name = key === SHEET_OVERLAPS ? key : key + "_clean"
    parseJsonToSheet(spreadsheet, name, val, namesLen + i);
  }
}

/**
 * Parse JSON string to sheet.
 * 
 * @param ss Spreadsheet.
 * @param name Name of sheet to create.
 * @param jsonData JSON string to insert into the sheet.
 * @param sheeti Index of sheet to add (0-based indexing).
 *
 * @return Inserted sheet.
 */
function parseJsonToSheet(ss, name, jsonData, sheeti) {
  var sheet = ss.insertSheet(name, sheeti);
  var jsonData = JSON.parse(jsonData);
  var jsonDataLen = jsonData.length;
  //Logger.log("name: " + name + ", jsonDataLen: " + jsonDataLen + ", jsonData: " + jsonData);
  var out = []
  for (var i = 0; i < jsonDataLen; i++) {
    var row = jsonData[i];
    if (i == 0) {
      //Logger.log("headers: " + Object.keys(row));
      out.push(Object.keys(row));
      //Logger.log("headers: " + out[0]);
    }
    out.push(Object.values(row));
  }
  Logger.log(name + " num rows: " + out.length + ", cols: " + out[0].length);
  sheet.getRange(1, 1, out.length, out[0].length).setValues(out);
  return sheet;
}

function parseCsvStrToSheet(ss, name, csvStr) {
  var data = Utilities.parseCsv(csvStr);
  var sheet = ss.insertSheet(name);
  sheet.getRange(1, 1, data.length, data[0].length).setValues(data);
}

/**
 * Convert the entire data range to CSV format.
 * @param {Sheet} sheet sheet to export
 * @return {string} sheet in CSV format
 */
function convertRangeToCsvStr(sheet) {
  // gets the range for all data in the sheet
  var activeRange = sheet.getDataRange();
  try {
    var data = activeRange.getValues();
    var dataLen = data.length;
    var csv = "";
    
    // ensures at least 2 rows, including header and a data row
    if (dataLen > 1) {
      for (var row = 0; row < dataLen; row++) { // rows
        var dataRowLen = data[row].length;
        for (var col = 0; col < dataRowLen; col++) { // columns
          data[row][col] = data[row][col].toString().replace(/\"/g, '""');
          if (data[row][col].toString().indexOf(",") != -1) {
            data[row][col] = "\"" + data[row][col] + "\"";
          }
        }
        
        // add newline unless last row
        if (row < dataLen - 1) {
          csv += data[row].join(",") + "\r\n";
        } else {
          csv += data[row];
        }
      }
    }
    return csv;
  } catch(err) {
    Logger.log(err);
  }
}

/**
 * Auto-resize columns of processing sheets, with upper limit
 * imposed by MAX_COL_WIDTH.
 */
function resizeColumns() {
  var sheets = getProcessedSheets();
  var sheetsLen = sheets.length;
  for (var i = 0; i < sheetsLen; i++) {
    var sheet = sheets[i];
    var lastColi = sheet.getLastColumn()
    for (var j = 1; j <= lastColi; j++) {
      // auto-resize column
      sheet.autoResizeColumn(j);
      if (sheet.getColumnWidth(j) > MAX_COL_WIDTH) {
        // reduce width if exceeds limit
        sheet.setColumnWidth(j, MAX_COL_WIDTH);
      }
    }
  }
}
