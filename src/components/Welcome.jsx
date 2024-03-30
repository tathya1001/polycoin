import React, { useState, useEffect } from "react";
import { useFirebase } from "../context/Firebase";

function Welcome(props) {
  const firebase = useFirebase();
  const [crediterName, setWelcomeerName] = useState("");
  const [leftAmount, setLeftAmount] = useState("");
  const [completedAmount, setCompletedAmount] = useState("");

  const currentDate = new Date();
  const hours = currentDate.getHours();

  // console.log(hours);

  let hourOfDay;

  if (5 <= hours && hours < 12) {
    hourOfDay = "Morning";
  } else if (12 <= hours && hours < 17) {
    hourOfDay = "Afternoon";
  } else if (17 <= hours && hours < 22) {
    hourOfDay = "Evening";
  } else if ((22 <= hours && hours < 24) || hours < 5) {
    hourOfDay = "Night";
  }

  return (
    <div className="flex flex-col gap-0 font-[Rubik] mt-1 mb-2">
      <span className="text-2xl text-white">Good {hourOfDay},</span>
      <span className="text-4xl font-semibold text-white">{props.name}</span>
    </div>
  );
}

export default Welcome;
