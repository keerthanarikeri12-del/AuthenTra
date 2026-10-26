// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice Credential registry indexing certificates by both referenceHash and fileHash.
/// No student names, grades, or documents are stored on-chain.
contract AuthenTraRegistry {
    address public immutable owner;
    mapping(address => bool) public approvedIssuers;

    struct Certificate {
        bytes32 fileHash;
        address issuer;
        uint64 registeredAt;
        bool revoked;
    }

    // Lookup by referenceHash: referenceHash => Certificate
    mapping(bytes32 => Certificate) public certificates;

    // Direct lookup by exact fileHash: fileHash => Certificate
    mapping(bytes32 => Certificate) public certificatesByHash;

    // Link fileHash back to referenceHash: fileHash => referenceHash
    mapping(bytes32 => bytes32) public referenceByFileHash;

    event IssuerApproval(address indexed issuer, bool approved);
    event Registered(bytes32 indexed referenceHash, bytes32 indexed fileHash, address indexed issuer);
    event Revoked(bytes32 indexed referenceHash, bytes32 indexed fileHash, address indexed actor);

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
        require(certificatesByHash[fileHash].issuer == address(0), "File hash exists");

        Certificate memory cert = Certificate(fileHash, msg.sender, uint64(block.timestamp), false);
        certificates[referenceHash] = cert;
        certificatesByHash[fileHash] = cert;
        referenceByFileHash[fileHash] = referenceHash;

        emit Registered(referenceHash, fileHash, msg.sender);
    }

    function revoke(bytes32 referenceHash) external {
        Certificate storage certificate = certificates[referenceHash];
        require(certificate.issuer != address(0), "Record missing");
        require(msg.sender == owner || (msg.sender == certificate.issuer && approvedIssuers[msg.sender]), "Not authorized");
        require(!certificate.revoked, "Already revoked");

        certificate.revoked = true;
        bytes32 fileHash = certificate.fileHash;
        if (certificatesByHash[fileHash].issuer != address(0)) {
            certificatesByHash[fileHash].revoked = true;
        }

        emit Revoked(referenceHash, fileHash, msg.sender);
    }

    function revokeByHash(bytes32 fileHash) external {
        Certificate storage cert = certificatesByHash[fileHash];
        require(cert.issuer != address(0), "Record missing");
        require(msg.sender == owner || (msg.sender == cert.issuer && approvedIssuers[msg.sender]), "Not authorized");
        require(!cert.revoked, "Already revoked");

        cert.revoked = true;
        bytes32 refHash = referenceByFileHash[fileHash];
        if (refHash != bytes32(0) && certificates[refHash].issuer != address(0)) {
            certificates[refHash].revoked = true;
        }

        emit Revoked(refHash, fileHash, msg.sender);
    }

    function lookupByHash(bytes32 fileHash) external view returns (
        bytes32 fileHashOut,
        address issuer,
        uint64 registeredAt,
        bool revoked,
        bytes32 referenceHash
    ) {
        Certificate storage cert = certificatesByHash[fileHash];
        return (cert.fileHash, cert.issuer, cert.registeredAt, cert.revoked, referenceByFileHash[fileHash]);
    }

    function lookupByReference(bytes32 referenceHash) external view returns (
        bytes32 fileHash,
        address issuer,
        uint64 registeredAt,
        bool revoked
    ) {
        Certificate storage cert = certificates[referenceHash];
        return (cert.fileHash, cert.issuer, cert.registeredAt, cert.revoked);
    }
}
