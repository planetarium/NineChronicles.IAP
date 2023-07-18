import {STAGE} from "./const.js";

export const stageUrl = (url) => {
  return `${STAGE === "local" ? "" : `/${STAGE}`}${url}`;
};
