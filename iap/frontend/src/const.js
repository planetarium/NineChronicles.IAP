export const BoxStatusColorMap = {
  1: "gray",
  2: "blue",
  3: "indigo",
  4: "purple",
  10: "green",
  90: "red",
  99: "red",
}

export const BoxStatusNameMap = {
  1: "Created",
  2: "Message Sent to Queue",
  3: "Tx Created",
  4: "Tx Staged",
  10: "Tx Success",
  90: "Tx Failed",
  99: "ERROR",
}

// Common Enums
// See common/enums.py
export const STORE_MAP = {
  0: "TEST",
  1: "APPLE",
  2: "GOOGLE",
  91: "APPLE_TEST",
  92: "GOOGLE_TEST",
};

export const RECEIPT_STATUS_MAP = {
  0: {
    Name: "INIT",
    Desc: "",
  },
  1: {
    Name: "VALIDATION_REQUEST",
    Desc: "",
  },
  10: {
    Name: "VALID",
    Desc: "",
  },
  20: {
    Name: "REFUND_BY_ADMIN",
    Desc: "",
  },
  91: {
    Name: "INVALID",
    Desc: "",
  },
  92: {
    Name: "REFUND_BY_BUYER",
    Desc: ""
  },
  99: {
    Name: "UNKNOWN",
    Desc: "",
  },
};

export const TxStatus = {
  1: "CREATED",
  2: "STAGED",
  10: "SUCCESS",
  91: "FAILURE",
  92: "INVALID",
  93: "NOT_FOUND",
  94: "FAIL_TO_CREATE",
  99: "UNKNOWN",
};

export const STAGE="local";
