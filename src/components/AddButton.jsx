import React, { useEffect, useState } from "react";
import { useFirebase } from "../context/Firebase";

const AddButton = ({ link, height }) => {
  const firebase = useFirebase();

  return (
    <a
      style={{ height: height }}
      className="min-w-12 bg-transparent flex flex-col justify-center items-center p-1 rounded-[1rem] gap-2 font-[Rubik] box-border border-dashed border-white border-[0.20rem]"
      href={link}
    >
      <svg className="w-5 fill-white" viewBox="0 0 448 512">
        <path d="M256 80c0-17.7-14.3-32-32-32s-32 14.3-32 32V224H48c-17.7 0-32 14.3-32 32s14.3 32 32 32H192V432c0 17.7 14.3 32 32 32s32-14.3 32-32V288H400c17.7 0 32-14.3 32-32s-14.3-32-32-32H256V80z" />
      </svg>
    </a>
  );
};

export default AddButton;
