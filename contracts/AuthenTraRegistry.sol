// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice Minimal credential registry. No names, grades or documents are stored.
contract AuthenTraRegistry {
    address public immutable owner;
    mapping(address => bool) public approvedIssuers;
    struct Certificate {
        bytes32 fileHash;
        address issuer;
        uint64 registeredAt;
        bool revoked;
    }
    mapping(bytes32 => Certificate) public certificates;
    event IssuerApproval(address indexed issuer, bool approved);
    event Registered(bytes32 indexed referenceHash, bytes32 fileHash, address indexed issuer);
    event Revoked(bytes32 indexed referenceHash, address indexed actor);

    constructor() { owner = msg.sender; }

    function setIssuer(address issuer, bool approved) external {
        require(msg.sender == owner, "Owner only");
        require(issuer != address(0), "Invalid issuer");
        approvedIssuers[issuer] = approved;
        emit IssuerApproval(issuer, approved);
    }

    function register(bytes32 referenceHash, bytes32 fileHash) external {
        require(approvedIssuers[msg.sender], "Approved issuer only");
        require(referenceHash != bytes32(0) && fileHash != bytes32(0), "Invalid hash");
        require(certificates[referenceHash].issuer == address(0), "Reference exists");
        certificates[referenceHash] = Certificate(fileHash, msg.sender, uint64(block.timestamp), false);
        emit Registered(referenceHash, fileHash, msg.sender);
    }

    function revoke(bytes32 referenceHash) external {
        Certificate storage certificate = certificates[referenceHash];
        require(certificate.issuer != address(0), "Record missing");
        require(msg.sender == owner || (msg.sender == certificate.issuer && approvedIssuers[msg.sender]), "Not authorized");
        require(!certificate.revoked, "Already revoked");
        certificate.revoked = true;
        emit Revoked(referenceHash, msg.sender);
    }
}
