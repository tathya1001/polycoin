import React, { useEffect, useState } from "react";
import { useFirebase } from "../context/Firebase";
import ProgressBar from "./ProgressBar";

import CurrencyComponent from "./CurrencyComponent.jsx";
const DebitCard = (props) => {
  const firebase = useFirebase();
  const [isPayPopupOpen, setIsPayPopupOpen] = useState(false);
  const [isAddPopupOpen, setIsAddPopupOpen] = useState(false);
  const [paymentInput, setPaymentInput] = useState("");
  const [additionInput, setAdditionInput] = useState("");

  const handleAddClick = () => {
    setIsAddPopupOpen(true);
  };

  const handleAddConfirm = () => {
    if (additionInput.trim() !== "") {
      firebase.handleDebitAdd(
        props.id,
        props.left,
        parseInt(additionInput),
        firebase.user.uid
      );
      setIsAddPopupOpen(false);
      setAdditionInput("");
    }
  };

  const handleAddCancel = () => {
    setIsAddPopupOpen(false);
    setAdditionInput("");
  };

  const handlePayClick = () => {
    setIsPayPopupOpen(true);
  };

  const handlePayConfirm = () => {
    if (paymentInput.trim() !== "") {
      firebase.handleDebitPay(
        props.id,
        props.completed,
        parseInt(paymentInput),
        firebase.user.uid
      );
      setIsPayPopupOpen(false);
      setPaymentInput("");
    }
  };

  const handlePayCancel = () => {
    setIsPayPopupOpen(false);
    setPaymentInput("");
  };

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

  return (
    props.left != props.completed && (
      <div className="h-24 bg-[#1D5F06] flex px-3 py-2 rounded-[1rem] gap-2 font-[Rubik] box-border">
        <div className="right-side w-32 text-white text-[1.35rem] flex flex-col justify-between">
          <span className="truncate">{props.name}</span>
          <ProgressBar
            maxValue={props.left}
            completedValue={props.completed}
          ></ProgressBar>
          <span className="font-medium">
            <CurrencyComponent />
            {props.left - props.completed}
          </span>
        </div>
        <div className="left-side flex flex-col justify-around">
          <button
            className="w-20 h-8 bg-white rounded-md text-[1.15rem] text-black"
            onClick={handleAddClick}
          >
            Add
          </button>
          <button
            className="w-20 h-8 bg-white rounded-md text-[1.15rem] text-black"
            onClick={handlePayClick}
          >
            Pay
          </button>
        </div>

        {isAddPopupOpen && (
          <div className="absolute top-0 left-0 w-full h-full flex items-center justify-center bg-gray-900 bg-opacity-50">
            <div className="bg-white p-4 rounded-md">
              <input
                type="number"
                value={additionInput}
                onChange={(e) => setAdditionInput(e.target.value)}
                className="w-full text-white border-gray-300 rounded-md p-2 focus:outline-none"
              />
              <div className="flex justify-between mt-4">
                <button
                  className="bg-red-500 text-white px-4 py-2 rounded-md mr-2"
                  onClick={handleAddCancel}
                >
                  Cancel
                </button>
                <button
                  className="bg-green-500 text-white px-4 py-2 rounded-md"
                  onClick={handleAddConfirm}
                >
                  Confirm
                </button>
              </div>
            </div>
          </div>
        )}

        {isPayPopupOpen && (
          <div className="absolute top-0 left-0 w-full h-full flex items-center justify-center bg-gray-900 bg-opacity-50">
            <div className="bg-white p-4 rounded-md">
              <input
                type="number"
                value={paymentInput}
                onChange={(e) => setPaymentInput(e.target.value)}
                className="w-full text-white border-gray-300 rounded-md p-2 focus:outline-none"
              />
              <div className="flex justify-between mt-4">
                <button
                  className="bg-red-500 text-white px-4 py-2 rounded-md mr-2"
                  onClick={handlePayCancel}
                >
                  Cancel
                </button>
                <button
                  className="bg-green-500 text-white px-4 py-2 rounded-md"
                  onClick={handlePayConfirm}
                >
                  Confirm
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  );
};

export default DebitCard;
