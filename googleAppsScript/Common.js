/**
 * Citation Overlap Google Apps Script Add-On
 * Stephan Sanders Lab, 2020, 2021
 * 
 * SCRIPT PROPERTIES
 * - SERVER_URL: set to server hosting Citation-Overlap flask app
 */

// name of sheet with database overlaps
SHEET_OVERLAPS = 'overlaps';

// maximum column width
MAX_COL_WIDTH = 300;

// Google Sheets max characters per cell
MAX_CHARS_PER_CELL = 50000;

// user properties stored across sessions
var userProps = PropertiesService.getUserProperties();

/**
 * Create a template from the index file to display as a web app.
 * 
 * @param {string} e optional event
 * @return {HtmlTemplate} the HTMLTemplate object
 */
function doGet(e) {
  // TESTING: test initial launch without properties
  // userProps.deleteAllProperties();

  // set up page
  var template = HtmlService.createTemplateFromFile('index');
  return template.evaluate().setSandboxMode(HtmlService.SandboxMode.IFRAME);
}

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

/**
 * Show a sidebar as an Add-on attached to a spreadsheet.
 */
function showSidebar() {
  var html = HtmlService.createTemplateFromFile("sidewrap").evaluate();
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
 * Create a new spreadsheet.
 * 
 * @return {str} The spreadsheet URL.
 */
function createSpreadsheet() {
  var spreadsheet = SpreadsheetApp.create("Citations");
  setCurrentSpreadsheet(spreadsheet.getUrl());
  return spreadsheet.getUrl();
}

/**
 * Get the spreadsheet URL user property.
 * 
 * @return {str} The saved spreadsheet URL user property.
 */
function getPropSpreadsheetURL() {
  return userProps.getProperty("spreadsheetURL");
}

/**
 * Set the current spreadsheet to a user property.
 * @param url URL of spreadsheet as a string.
 */
function setCurrentSpreadsheet(url) {
  // setting the active spreadsheet does not appear to work beyond this fn
  //var activeSpreadsheet = SpreadsheetApp.openByUrl(url);
  //SpreadsheetApp.setActiveSpreadsheet(activeSpreadsheet);
  userProps.setProperty("spreadsheetURL", url);
  console.log("active set " + userProps.getProperty("spreadsheetURL"));
}

/**
 * Get the current spreadsheeet.
 * @return {Spreadsheet} The active spreadsheet if available; if not, the
 * spreadsheet set in the user property.
 */
function getCurrentSpreadsheet() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  if (spreadsheet == null) {
    spreadsheet = SpreadsheetApp.openByUrl(getPropSpreadsheetURL());
  }
  return spreadsheet;
}

/**
 * Set up empty sheets with database names.
 * 
 * @param {str} names Names given as a comma-delimited string; all spaces
 * will be removed.
 */
function setupSheets(names) {
  var spreadsheet = getCurrentSpreadsheet();
  var dbNames = names.replace(/ /g, "").split(",");
  var namesLen = dbNames.length;
  for (var i = 0; i < namesLen; i++) {
    spreadsheet.insertSheet(dbNames[i], i);
  }
  spreadsheet.setActiveSheet(spreadsheet.getSheetByName(dbNames[0]));
}

/**
 * Get processed sheets as identified by suffix or as the overlaps sheet.
 *
 * @return Array of processed sheets.
 */
function getProcessedSheets() {
  var spreadsheet = getCurrentSpreadsheet();
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
  var spreadsheet = getCurrentSpreadsheet();
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
 * 
 * @param dbNames {array} List of valid database names; only sheets
 * matching these names will be processed.
 */
function findOverlaps(dbNames) {
  var spreadsheet = getCurrentSpreadsheet();
  var sheets = spreadsheet.getSheets();
  var sheetsLen = sheets.length;
  var namesLen = dbNames.length;
  
  // convert database sheets to CSV strings
  var data = {};
  for (var i = 0; i < sheetsLen; i++) {
    var sheet = sheets[i];
    var sheetName = sheet.getName();
    for (var j = 0; j < namesLen; j++) {
      if (sheetName.toLowerCase().startsWith(dbNames[j].toLowerCase())) {
        // only process sheets whose name matches a database name
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
  var namesOv = Object.keys(data);
  var nData = namesOv.length;
  namesOv.push(SHEET_OVERLAPS);
  var namesOvLen = namesOv.length;
  for (var i = 0; i < namesOvLen; i++) {
    var key = namesOv[i]
    var val = respData[key];
    Logger.log("key: " + key + ", val: " + val.slice(-200));
    var name = key === SHEET_OVERLAPS ? key : key + "_clean"
    parseJsonToSheet(spreadsheet, name, val, nData + i);
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

/**
 * Parse CSV file given as a string into a new sheet.
 * 
 * @param {str} name Name of new sheet to enter. If the currently active
 * sheet is empty, this sheet will be renamed and used instead.
 * @param {str} csvStr CSV file contents given as a string.
 * @param {Spreadsheet} Spreadsheet instance; defaults to null to get
 * the current spreadsheet.
 */
function parseCsvStrToSheet(name, csvStr, ss=null) {
  if (ss == null) {
    // default to get the current spreadsheet
    ss = getCurrentSpreadsheet();
  }

  // parse the CSV and enter into a sheet
  var data = Utilities.parseCsv(csvStr);
  var sheet = ss.getActiveSheet();
  if (sheet.getLastRow() == 0) {
    // use the active sheet if empty and rename it
    sheet.setName(name);
  } else {
    // create a new sheet and insert at end of sheets
    sheet = ss.insertSheet(name, ss.getNumSheets());
  }
  
  // truncate to max char per cell limit and insert into sheet
  var dataLen = data.length;
  for (var row = 0; row < dataLen; row++) { // rows
    var dataRowLen = data[row].length;
    for (var col = 0; col < dataRowLen; col++) { // columns
      cell = data[row][col];
      if (cell.length > MAX_CHARS_PER_CELL) {
        data[row][col] = cell.substring(0, MAX_CHARS_PER_CELL);
      }
    }
  }
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
