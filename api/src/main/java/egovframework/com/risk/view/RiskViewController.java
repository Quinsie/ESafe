package egovframework.com.risk.view;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

@Controller
public class RiskViewController {

    @Value("${risk.map.vworld.apiKey:}")
    private String vworldApiKey;

    @RequestMapping("/login.do")
    public String login() {
        return "risk/login";
    }

    @RequestMapping("/accessDenied.do")
    public String accessDenied() {
        return "risk/accessDenied";
    }

    @RequestMapping("/riskDashboard.do")
    public String dashboard() {
        return "risk/dashboard";
    }

    @RequestMapping("/riskBuildingList.do")
    public String buildingList() {
        return "risk/buildingList";
    }

    @RequestMapping("/riskBuildingDetail.do")
    public String buildingDetail(@RequestParam("bldgSeq") long bldgSeq, Model model) {
        model.addAttribute("bldgSeq", bldgSeq);
        model.addAttribute("vworldApiKey", vworldApiKey);
        return "risk/buildingDetail";
    }

    @RequestMapping("/riskFacilityGeneralDetail.do")
    public String facilityGeneralDetail(
            @RequestParam("histSeq") long histSeq,
            @RequestParam(value = "bldgSeq", required = false) Long bldgSeq,
            Model model) {
        model.addAttribute("histSeq", histSeq);
        model.addAttribute("facilityType", "GENERAL");
        model.addAttribute("bldgSeq", bldgSeq);
        return "risk/facilityGeneralDetail";
    }

    @RequestMapping("/riskFacilitySelfDetail.do")
    public String facilitySelfDetail(
            @RequestParam("histSeq") long histSeq,
            @RequestParam(value = "bldgSeq", required = false) Long bldgSeq,
            Model model) {
        model.addAttribute("histSeq", histSeq);
        model.addAttribute("facilityType", "SELF");
        model.addAttribute("bldgSeq", bldgSeq);
        return "risk/facilitySelfDetail";
    }

    @RequestMapping("/riskWeatherAlert.do")
    public String weatherAlert(Model model) {
        model.addAttribute("vworldApiKey", vworldApiKey);
        return "risk/weatherAlert";
    }

    @RequestMapping("/riskBranchSummary.do")
    public String branchSummary() {
        return "risk/branchSummary";
    }

    @RequestMapping("/riskRegionSummary.do")
    public String regionSummary() {
        return "risk/regionSummary";
    }

    @RequestMapping("/riskNationwideRiskMap.do")
    public String nationwideRiskMap(Model model) {
        model.addAttribute("vworldApiKey", vworldApiKey);
        return "risk/nationwideRiskMap";
    }
}
