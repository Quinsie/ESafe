package egovframework.com.risk.vo;

import java.io.Serializable;
import java.util.List;

public class RiskSearchVO implements Serializable {

    private static final long serialVersionUID = 1L;
    private static final int DEFAULT_PAGE_SIZE = 20;
    private static final int MAX_PAGE_SIZE = 500;

    private int pageIndex = 1;
    private int pageSize = DEFAULT_PAGE_SIZE;
    private int firstIndex;

    private String hqNm;
    private String branchNm;
    private List<String> branchNmList;
    private String regionNm;
    private String districtNm;
    private String riskCd;
    private String combinedRiskCd;
    private String gradeChangedYn;
    private String searchKeyword;
    private String alertDate;
    private String startDate;
    private String endDate;

    public void calcFirstIndex() {
        if (this.pageIndex < 1) {
            this.pageIndex = 1;
        }
        if (this.pageSize < 1) {
            this.pageSize = DEFAULT_PAGE_SIZE;
        } else if (this.pageSize > MAX_PAGE_SIZE) {
            this.pageSize = MAX_PAGE_SIZE;
        }
        this.firstIndex = (this.pageIndex - 1) * this.pageSize;
    }

    public int getPageIndex() { return pageIndex; }
    public void setPageIndex(int pageIndex) {
        this.pageIndex = (pageIndex < 1) ? 1 : pageIndex;
    }

    public int getPageSize() { return pageSize; }
    public void setPageSize(int pageSize) {
        if (pageSize < 1) {
            this.pageSize = DEFAULT_PAGE_SIZE;
        } else if (pageSize > MAX_PAGE_SIZE) {
            this.pageSize = MAX_PAGE_SIZE;
        } else {
            this.pageSize = pageSize;
        }
    }

    public int getFirstIndex() { return firstIndex; }
    public void setFirstIndex(int firstIndex) { this.firstIndex = firstIndex; }

    public String getHqNm() { return hqNm; }
    public void setHqNm(String hqNm) { this.hqNm = hqNm; }

    public String getBranchNm() { return branchNm; }
    public void setBranchNm(String branchNm) { this.branchNm = branchNm; }

    public List<String> getBranchNmList() { return branchNmList; }
    public void setBranchNmList(List<String> branchNmList) { this.branchNmList = branchNmList; }

    public String getRegionNm() { return regionNm; }
    public void setRegionNm(String regionNm) { this.regionNm = regionNm; }

    public String getDistrictNm() { return districtNm; }
    public void setDistrictNm(String districtNm) { this.districtNm = districtNm; }

    public String getRiskCd() { return riskCd; }
    public void setRiskCd(String riskCd) { this.riskCd = riskCd; }

    public String getCombinedRiskCd() { return combinedRiskCd; }
    public void setCombinedRiskCd(String combinedRiskCd) { this.combinedRiskCd = combinedRiskCd; }

    public String getGradeChangedYn() { return gradeChangedYn; }
    public void setGradeChangedYn(String gradeChangedYn) { this.gradeChangedYn = gradeChangedYn; }

    public String getSearchKeyword() { return searchKeyword; }
    public void setSearchKeyword(String searchKeyword) { this.searchKeyword = searchKeyword; }

    public String getAlertDate() { return alertDate; }
    public void setAlertDate(String alertDate) { this.alertDate = alertDate; }

    public String getStartDate() { return startDate; }
    public void setStartDate(String startDate) { this.startDate = startDate; }

    public String getEndDate() { return endDate; }
    public void setEndDate(String endDate) { this.endDate = endDate; }
}
