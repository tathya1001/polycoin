import React, { useEffect, useState } from "react";
import { useFirebase } from "../context/Firebase.jsx";

import CustomIcon from "./CustomIcon.jsx"

import CurrencyComponent from "./CurrencyComponent.jsx";

const HeroCard = (props) => {
    const firebase = useFirebase();

    const [books, setBooks] = useState([]);



    const [currency, setCurrency] = useState('');

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


    let iconPath;
    let bgColor;
    let textColor;

    switch (props.title) {
        case "Expense":
            iconPath = <svg fill="#AF2525" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512"><path d="M214.6 9.4c-12.5-12.5-32.8-12.5-45.3 0l-128 128c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L160 109.3V480c0 17.7 14.3 32 32 32s32-14.3 32-32V109.3l73.4 73.4c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3l-128-128z" /></svg>;
            bgColor = "#FFE5E5";
            textColor="#AF2525";
            break;
        case "Income":
            iconPath = <svg fill="#265914" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512"><path d="M169.4 502.6c12.5 12.5 32.8 12.5 45.3 0l128-128c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L224 402.7 224 32c0-17.7-14.3-32-32-32s-32 14.3-32 32l0 370.7L86.6 329.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l128 128z" /></svg>;
            bgColor = "#F4FFF0";
            textColor="#265914";
            break;
        default:
            break;
    }

    return (



        <div className="text-white w-[50%] min-w-36 sm:max-w-36 flex flex-col justify-between px-2.5 py-1.5 rounded-xl font-[Rubik] box-border " style={{ backgroundColor: bgColor }}>

            <span className="text-sm font-medium opacity-50" style={{ color: textColor }}>{props.title}</span>

            <div className="bottom-side flex flex-row justify-between">
                <div className="w-6">
                    {iconPath}
                </div>
                <span className="font-bold text-3xl items-self-end" style={{ color: textColor }}><CurrencyComponent />{props.trans}</span>

            </div>



        </div >
    );
};

export default HeroCard;