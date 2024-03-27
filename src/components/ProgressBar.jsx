import React from "react";

const ProgressBar = ({ maxValue, completedValue }) => {
    const calculatePercentage = () => {
        if (maxValue <= 0) {
            return 0;
        }
        return (completedValue / maxValue) * 100;
    };

    const percentage = calculatePercentage();

    return (
        <div className="progress" style={{ height: "0.25rem",backgroundColor: "#FFFFFF55" ,backgroundOpacity: "0.75" }}>
            <div
                className="progress-bar opacity-100"
                role="progressbar"
                style={{ width: `${percentage}%`, backgroundColor: "#FFFFFF" }}
                aria-valuenow={percentage}
                aria-valuemin="0"
                aria-valuemax="100"
            >
            </div>
        </div>
    );
};

export default ProgressBar;
