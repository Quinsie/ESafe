package egovframework.com.risk.vo;

import java.io.Serializable;

public class RiskFacilityHistoryVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private String facilityType;
    private String branchNm;
    private String addr;
    private String kepcoCustNo;
    private String resultText;
    private String oralNoticeYn;
    private String failDetail;
    private String lineNo;
    private String capacity;
    private String checkCycle;
    private String contractType;
    private Integer defectCnt;
    private String motorType;
    private String checkDt;
    private Long histSeq;

    public String getFacilityType() {
        return facilityType;
    }

    public void setFacilityType(String facilityType) {
        this.facilityType = facilityType;
    }

    public String getBranchNm() {
        return branchNm;
    }

    public void setBranchNm(String branchNm) {
        this.branchNm = branchNm;
    }

    public String getAddr() {
        return addr;
    }

    public void setAddr(String addr) {
        this.addr = addr;
    }

    public String getKepcoCustNo() {
        return kepcoCustNo;
    }

    public void setKepcoCustNo(String kepcoCustNo) {
        this.kepcoCustNo = kepcoCustNo;
    }

    public String getResultText() {
        return resultText;
    }

    public void setResultText(String resultText) {
        this.resultText = resultText;
    }

    public String getOralNoticeYn() {
        return oralNoticeYn;
    }

    public void setOralNoticeYn(String oralNoticeYn) {
        this.oralNoticeYn = oralNoticeYn;
    }

    public String getFailDetail() {
        return failDetail;
    }

    public void setFailDetail(String failDetail) {
        this.failDetail = failDetail;
    }

    public String getLineNo() {
        return lineNo;
    }

    public void setLineNo(String lineNo) {
        this.lineNo = lineNo;
    }

    public String getCapacity() {
        return capacity;
    }

    public void setCapacity(String capacity) {
        this.capacity = capacity;
    }

    public String getCheckCycle() {
        return checkCycle;
    }

    public void setCheckCycle(String checkCycle) {
        this.checkCycle = checkCycle;
    }

    public String getContractType() {
        return contractType;
    }

    public void setContractType(String contractType) {
        this.contractType = contractType;
    }

    public Integer getDefectCnt() {
        return defectCnt;
    }

    public void setDefectCnt(Integer defectCnt) {
        this.defectCnt = defectCnt;
    }

    public String getMotorType() {
        return motorType;
    }

    public void setMotorType(String motorType) {
        this.motorType = motorType;
    }

    public String getCheckDt() {
        return checkDt;
    }

    public void setCheckDt(String checkDt) {
        this.checkDt = checkDt;
    }

    public Long getHistSeq() {
        return histSeq;
    }

    public void setHistSeq(Long histSeq) {
        this.histSeq = histSeq;
    }
}
