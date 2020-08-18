/**
 * Citation Overlap Google Apps Script Add-On
 * Stephan Sanders Lab, 2020
 */

// database names
DB_NAMES = [
  'medline',
  'embase',
  'scopus'
];

// name of sheet with database overlaps
SHEET_OVERLAPS = 'overlaps';

/**
 * Add a custom menu when the user opens the spreadsheet.
 */
function onOpen(e) {
  var menu = SpreadsheetApp.getUi().createAddonMenu();
  menu.addItem('Set up sheets', 'setupSheets');
  menu.addItem('Find overlaps', 'findOverlaps');
  menu.addItem('Remove processed sheets', 'clearSheets');
//  if (e && e.authMode == ScriptApp.AuthMode.NONE) {
//    menu.addItem('Find overlaps', 'findOverlaps');
//  } else {
//    // TODO: add functionality requiring authoriziation
//    menu.addItem('Find overlaps', 'findOverlaps');
//  }
  menu.addToUi();
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
}

/**
 * Clear processed sheets.
 */
function clearSheets() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheetsLen = DB_NAMES.length;
  var sheetsToRemove = [SHEET_OVERLAPS + '_clean'];
  for (var i = 0; i < sheetsLen; i++) {
    sheetsToRemove.push(DB_NAMES[i] + '_clean');
  }
  var remLen = sheetsToRemove.length;
  for (var i = 0; i < remLen; i++) {
    var sheet = spreadsheet.getSheetByName(sheetsToRemove[i]);
    if (sheet != null) {
      spreadsheet.deleteSheet(sheet);
    }
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
  var data = {};
  for (var i = 0; i < sheetsLen; i++) {
    var sheet = sheets[i];
    var sheetName = sheet.getName();
    for (var j = 0; j < namesLen; j++) {
      if (sheetName.startsWith(DB_NAMES[j])) {
        csv = convertRangeToCsvFile(sheet);
        Logger.log("sheet " + sheetName)
        data[sheetName] = csv;
        break;
      }
    }
  }
  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(data)
  };
  //Logger.log("options: " + options["payload"]);
  var response = UrlFetchApp.fetch(
    PropertiesService.getScriptProperties().getProperty('SERVER_URL'), options);
  var json = response.getContentText()
  //Logger.log("response: " + json);
  var respData = JSON.parse(json);
  //parseCsvStrToSheet(spreadsheet, "overlaps", respData);
  //var sheet = spreadsheet.insertSheet("overlaps", spreadsheet.getNumSheets() + 1);
  //sheet.getRange(1, 1, respData.length, respData[0].length).setValues(respData);
  var respDataLen = respData.length;
  for (const [key, val] of Object.entries(respData)) {
    Logger.log("key: " + key + ", val: " + val.slice(-200));
    parseJsonToSheet(spreadsheet, key + "_clean", respData[key]);
  }
}

/**
 * Parse JSON string to sheet.
 * 
 * @param ss Spreadsheet.
 * @param name Name of sheet to create.
 * @param jsonData JSON string to insert into the sheet.
 */
function parseJsonToSheet(ss, name, jsonData) {
  var sheet = ss.insertSheet(name, ss.getNumSheets() + 1);
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
function convertRangeToCsvFile(sheet) {
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
