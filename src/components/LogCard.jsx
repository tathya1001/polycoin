import React, { useEffect, useState } from "react";
import { useFirebase } from "../context/Firebase";

import CustomIcon from "./CustomIcon.jsx";
import CurrencyComponent from "./CurrencyComponent.jsx";

const LogCard = (props) => {
  const firebase = useFirebase();

  const [books, setBooks] = useState([]);
  const [categoryDetails, setCategoryDetails] = useState([]);

  let colorCode;
  let option = categoryDetails.colorid;

  switch (option) {
    case 1:
      colorCode = "#FD2741";
      break;
    case 2:
      colorCode = "#458FFF";
      break;
    case 3:
      colorCode = "#FFA800";
      break;
    case 4:
      colorCode = "#48BB45";
      break;
    case 5:
      colorCode = "#BC58EB";
      break;
    case 6:
      colorCode = "#F460C2";
      break;
    case 7:
      colorCode = "#FF810D";
      break;
    default:
      colorCode = "#858585";
      break;
  }

  useEffect(() => {
    if (firebase.user) {
      const fetchCategoryData = async () => {
        const categoryData = await firebase.getCategoryData(
          firebase.user.uid,
          props.categoryid
        );
        if (categoryData) {
          setCategoryDetails(categoryData);
        }
      };

      fetchCategoryData();
    }
  }, [firebase.user]);

  const [currency, setCurrency] = useState("");

  useEffect(() => {
    if (firebase.user) {
      const fetchUserData = async () => {
        const userData = await firebase.getUserData(firebase.user.uid);
        if (userData) {
          setCurrency(userData.currencyID);
        }
      };

      fetchUserData();
    }
  }, [firebase.user]);

  // console.log(currency);

  return (
    // (props.categoryid == 1 && (
    //     <div
    //         className="min-h-16 max-h-16 flex flex-row justify-between items-center px-3 py-1 rounded-[0.75rem] font-[Rubik] box-border text-lime-500"
    //         style={{ backgroundColor: "transparent" }}
    //     >
    //         <div className="w-72 flex flex-row items-center gap-3">
    //             <div className="min-w-8 max-w-8">
    //                 <svg
    //                     className="fill-lime-500"
    //                     xmlns="http://www.w3.org/2000/svg"
    //                     viewBox="0 0 576 512"
    //                 >
    //                     <path d="M400 96l0 .7c-5.3-.4-10.6-.7-16-.7H256c-16.5 0-32.5 2.1-47.8 6c-.1-2-.2-4-.2-6c0-53 43-96 96-96s96 43 96 96zm-16 32c3.5 0 7 .1 10.4 .3c4.2 .3 8.4 .7 12.6 1.3C424.6 109.1 450.8 96 480 96h11.5c10.4 0 18 9.8 15.5 19.9l-13.8 55.2c15.8 14.8 28.7 32.8 37.5 52.9H544c17.7 0 32 14.3 32 32v96c0 17.7-14.3 32-32 32H512c-9.1 12.1-19.9 22.9-32 32v64c0 17.7-14.3 32-32 32H416c-17.7 0-32-14.3-32-32V448H256v32c0 17.7-14.3 32-32 32H192c-17.7 0-32-14.3-32-32V416c-34.9-26.2-58.7-66.3-63.2-112H68c-37.6 0-68-30.4-68-68s30.4-68 68-68h4c13.3 0 24 10.7 24 24s-10.7 24-24 24H68c-11 0-20 9-20 20s9 20 20 20H99.2c12.1-59.8 57.7-107.5 116.3-122.8c12.9-3.4 26.5-5.2 40.5-5.2H384zm64 136a24 24 0 1 0 -48 0 24 24 0 1 0 48 0z" />
    //                 </svg>
    //             </div>
    //             <div className="flex flex-col items-start justify-center w-32">
    //                 <div className="font-medium text-lg truncate">{props.name}</div>
    //                 <div className="font-regular text-xs opacity-75">{props.day} / {props.month} / {props.year}</div>
    //             </div>
    //         </div>
    //         <div className="font-regular text-xl justify-self-end font-semibold">
    //             <CurrencyComponent />
    //             {props.transaction}
    //         </div>
    //     </div>
    // )) ||

    // <div className="min-h-16 max-h-16 flex flex-row justify-between items-center px-3 py-1 rounded-[0.75rem] font-[Rubik] box-border text-white" style={{ backgroundColor: colorCode }}>
    //     <div className="w-72 flex flex-row items-center gap-3">
    //         <div className="min-w-8 max-w-8 flex justify-center items-center">
    //             <CustomIcon icon={categoryDetails.iconid} height={"2rem"} />
    //         </div>
    //         <div className="flex flex-col items-start justify-center w-32">
    //             <div className="font-medium text-lg truncate">{props.name}</div>
    //             <div className="font-regular text-xs opacity-75">{props.day} / {props.month} / {props.year}</div>
    //         </div>
    //     </div>
    //     <div className="font-regular text-xl justify-self-end font-semibold"><CurrencyComponent />{props.transaction}</div>
    // </div>
    (props.categoryid == 1 && (
      <div
        className="min-h-16 max-h-16 grid grid-cols-12 gap-3 md:gap-2 lg:gap-1 px-3 lg:px-2 rounded-[0.75rem] font-[Rubik] box-border text-lime-500"
        style={{ backgroundColor: "transparent" }}
      >
        <div className="flex justify-center items-center col-span-2 md:col-span-1 lg:col-span-2">
          <svg
            className="fill-lime-500"
            height="1.75rem"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 576 512"
          >
            <path d="M400 96l0 .7c-5.3-.4-10.6-.7-16-.7H256c-16.5 0-32.5 2.1-47.8 6c-.1-2-.2-4-.2-6c0-53 43-96 96-96s96 43 96 96zm-16 32c3.5 0 7 .1 10.4 .3c4.2 .3 8.4 .7 12.6 1.3C424.6 109.1 450.8 96 480 96h11.5c10.4 0 18 9.8 15.5 19.9l-13.8 55.2c15.8 14.8 28.7 32.8 37.5 52.9H544c17.7 0 32 14.3 32 32v96c0 17.7-14.3 32-32 32H512c-9.1 12.1-19.9 22.9-32 32v64c0 17.7-14.3 32-32 32H416c-17.7 0-32-14.3-32-32V448H256v32c0 17.7-14.3 32-32 32H192c-17.7 0-32-14.3-32-32V416c-34.9-26.2-58.7-66.3-63.2-112H68c-37.6 0-68-30.4-68-68s30.4-68 68-68h4c13.3 0 24 10.7 24 24s-10.7 24-24 24H68c-11 0-20 9-20 20s9 20 20 20H99.2c12.1-59.8 57.7-107.5 116.3-122.8c12.9-3.4 26.5-5.2 40.5-5.2H384zm64 136a24 24 0 1 0 -48 0 24 24 0 1 0 48 0z" />
          </svg>
        </div>

        <div className="flex flex-col items-start justify-center col-span-8 md:col-span-9 lg:col-span-7">
          <span className="font-medium text-lg truncate">{props.name}</span>
          <span className="font-regular text-xs opacity-75">
            {props.day} / {props.month} / {props.year}
          </span>
        </div>

        <div className="flex justify-end items-center col-span-2 md:col-span-2 lg:col-span-3">
          <div className="font-regular text-xl justify-self-end font-semibold">
            <CurrencyComponent />
            {props.transaction}
          </div>
        </div>
      </div>
    )) ||
    (props.categoryid != 1 && (
      <div
        className="min-h-16 max-h-16 grid grid-cols-12 gap-3 md:gap-1 lg:gap-1 px-3 lg:px-2 rounded-[0.75rem] font-[Rubik] box-border text-white"
        style={{ backgroundColor: colorCode }}
      >
        <div className="flex justify-center items-center col-span-2 md:col-span-1 lg:col-span-2">
          <CustomIcon icon={categoryDetails.iconid} height={"1.75rem"} />
        </div>

        <div className="flex flex-col items-start justify-center col-span-8 md:col-span-9 lg:col-span-7">
          <span className="font-medium text-lg truncate">{props.name}</span>
          <span className="font-regular text-xs opacity-75">
            {props.day} / {props.month} / {props.year}
          </span>
        </div>

        <div className="flex justify-end items-center col-span-2 md:col-span-2 lg:col-span-3">
          <div className="font-regular text-xl justify-self-end font-semibold">
            <CurrencyComponent />
            {props.transaction}
          </div>
        </div>
      </div>
    ))
  );
};

export default LogCard;
