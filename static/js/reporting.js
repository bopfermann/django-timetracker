/*global $,alert,window*/
function isNumber(n) {
	"use strict";
	return !isNaN(parseFloat(n)) && isFinite(n);
}

function overtime_data() {
	"use strict";
	"use strict";
    var year =  $("#yearbox_ot_for_hr").val();
    if (isNumber(year) && year.length >= 4) {
        window.location.assign([
			"/reporting/ot_for_hr/",
            year + "/",
            $("#monthbox_hr").val() + "/"
		].join("")
							  );
    } else {
        $("#yearbox_hol").text("");
        alert("Invalid year.");
    }

}

function all_holiday_data() {
	"use strict";
    if ($("#user_select").val() === "null") {
        return;
    }
    window.location.assign(
        "/reporting/all/" + $("#user_select").val()  + "/"
    );
}

function yearmonth_holiday_data() {
	"use strict";
    var year =  $("#yearbox_hol").val();
    if (isNumber(year) && year.length >= 4) {
        window.location.assign([
			"/reporting/yearmonthhol/",
            year + "/",
            $("#monthbox_hol").val() + "/"
		].join("")
							  );
    } else {
        $("#yearbox_hol").text("");
        alert("Invalid year.");
    }
}

function ot_by_month() {
	"use strict";
    var year = $("#yearbox_ot_month").val();
    if (isNumber(year) && year.length >= 4) {
        window.location.assign([
			"/reporting/ot_by_month/",
            year + "/",
            $("#monthbox_ot").val() + "/"
		].join("")
							  );
    } else {
        $("#yearbox_hol").text("");
        alert("Invalid year.");
    }
}

function ot_by_year() {
	"use strict";
    var year = $("#yearbox_ot_year").val();
    if (isNumber(year) && year.length >= 4) {
        window.location.assign([
			"/reporting/ot_by_year/",
            year + "/",
        ].join("")
							  );
    } else {
        $("#yearbox_ot_year").text("");
        alert("Invalid year.");
    }
}

function holidays_for_yearmonth() {
	"use strict";
    var year = $("#yearbox_hols_year").val();
    if (isNumber(year) && year.length >= 4) {
        window.location.assign([
			"/reporting/hols_for_yearmonth/",
            year + "/"
        ].join("")
							  );
    } else {
        $("#yearbox_hols_year").text("");
        alert("Invalid year.");
    }
}

function all_team() {
    "use strict";

    var year = $("#yearbox_hols_year").val(),
        month = $("#monthbox_all").val(),
        team = $("#teambox_all").val();

    if (isNumber(year) && year.length >= 4) {
        window.location.assign([
			"/reporting/all_team/",
            year + "/",
            month + "/",
            team + "/"
        ].join("")
							  );
    } else {
        $("#yearbox_hols_year").text("");
        alert("Invalid year.");
    }

}
