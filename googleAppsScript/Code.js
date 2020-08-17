
/**
 * Add a custom menu when the user opens the spreadsheet.
 */
function onOpen() {
  var sheet = SpreadsheetApp.getActive();
  var entries = [{name : "Find overlaps", functionName : "findOverlaps"}, 
                ];
  sheet.addMenu("Citation Overlap", entries);
}

function findOverlaps() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = spreadsheet.getSheets();
  var sheetsLen = sheets.length;
  var data = {};
  for (var i = 0; i < sheetsLen; i++) {
    csv = convertRangeToCsvFile(sheets[i]);
    Logger.log("sheet " + sheets[i].getName())
    data[sheets[i].getName()] = csv;//.substring(0, 10);
  }
  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(data)
  };
  //Logger.log("options: " + options["payload"]);
  var response = UrlFetchApp.fetch(
    PropertiesService.getUserProperties().getProperty('SERVER_URL'), options);
  var json = response.getContentText()
  //Logger.log("response: " + json);
  //Logger.log("sub: " + json.substring(361000, 361300));
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
//        if (row >= 349 && row <= 351) {
//          Logger.log("row " + row + ":" + data[row]);
//        }
      }
    }
    return csv;
  } catch(err) {
    Logger.log(err);
  }
}
